import os
import sys
import logging
import cv2
import numpy as np

from openvino.runtime import Core
from scipy.spatial.distance import cosine
from cryptography.fernet import Fernet
from db_utils import get_connection
from config_store import get_fernet_key
from utils import resource_path

logger = logging.getLogger(__name__)

PROCESS_WIDTH, PROCESS_HEIGHT = 960, 540
CONF_THRESHOLD = 0.75
SIM_THRESHOLD = 0.75
LIVENESS_REAL_THRESHOLD = 0.85
MIN_REC_FACE_SIZE = 90
MIN_REC_BRIGHTNESS = 35.0
MAX_REC_BRIGHTNESS = 230.0
MIN_REC_SHARPNESS = 45.0

DET_MODEL = resource_path("models/intel/face-detection-adas-0001/FP16/face-detection-adas-0001.xml")
REC_MODEL = resource_path("models/intel/face-reidentification-retail-0095/FP16/face-reidentification-retail-0095.xml")
SPOOF_MODEL = resource_path("models/intel/anti-spoof-mn3/anti-spoof-mn3.onnx")
_ie = Core()

def _load_model(model_path, preferred=("GPU", "CPU")):
    for device in preferred:
        try:
            return _ie.compile_model(_ie.read_model(model_path), device)
        except Exception:
            continue
    return None

_det_model = _load_model(DET_MODEL)
_rec_model = _load_model(REC_MODEL)
_spoof_model = _load_model(SPOOF_MODEL)

_det_h, _det_w = _det_model.input(0).shape[2:] if _det_model else (0, 0)
_rec_h, _rec_w = _rec_model.input(0).shape[2:] if _rec_model else (0, 0)
_spoof_h, _spoof_w = _spoof_model.input(0).shape[2:] if _spoof_model else (0, 0)

_det_req = _det_model.create_infer_request() if _det_model else None
_gallery_cache = None

def _get_fernet():
    key = get_fernet_key()
    if not key:
        raise ValueError("Fernet key not configured.")
    return Fernet(key.encode() if isinstance(key, str) else key)

def _get_openvino_libs():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "openvino_libs")
    return os.path.join(os.path.dirname(__file__), "venv", "Lib", "site-packages", "openvino", "libs")

_openvino_libs = _get_openvino_libs()
if os.path.exists(_openvino_libs):
    os.environ["PATH"] = _openvino_libs + os.pathsep + os.environ.get("PATH", "")

def load_gallery(force_reload=False):
    global _gallery_cache
    if _gallery_cache is not None and not force_reload:
        return _gallery_cache
    conn = None
    cur = None
    rows = []

    try:
        conn, source = get_connection("local")
        cur = conn.cursor()
        cur.execute("""
            SELECT student_no, facial_recognition_data
            FROM students
            WHERE has_facial_recognition = TRUE
        """)
        rows = cur.fetchall()
    except Exception:
        logger.exception("Failed to load facial gallery from database")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    gallery = {}
    for sid, blob in rows:
        if not blob:
            continue
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        elif isinstance(blob, str):
            try:
                blob = bytes.fromhex(blob)
            except ValueError:
                import base64
                try:
                    blob = base64.b64decode(blob)
                except Exception:
                    blob = blob.encode("utf-8")
        try:
            fernet = _get_fernet()
            decrypted = fernet.decrypt(blob)
            embedding = np.frombuffer(decrypted, dtype=np.float32)
            if embedding.size > 0:
                gallery[sid] = {"embedding": embedding}
        except Exception as e:
            logger.warning("Failed to decrypt facial data for student %s: %s", sid, e)

    _gallery_cache = gallery
    return _gallery_cache

def reset_models():
    global _det_model, _rec_model, _spoof_model, _det_req, _gallery_cache
    _gallery_cache = None
    try:
        _det_model = _load_model(DET_MODEL)
        _rec_model = _load_model(REC_MODEL)
        _spoof_model = _load_model(SPOOF_MODEL)
        _det_req = _det_model.create_infer_request() if _det_model else None
    except Exception:
        logger.exception("Failed to reset face recognition models")

def preprocess(img, h, w, rgb=False):
    resized = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    if rgb:
        resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    blob = np.transpose(resized, (2, 0, 1))[None].astype(np.float32, copy=False)
    return blob

def _normalize_lighting(face_crop):
    lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

def _face_quality_ok(face_crop):
    if face_crop is None or face_crop.size == 0:
        return False
    h, w = face_crop.shape[:2]
    if min(h, w) < MIN_REC_FACE_SIZE:
        return False
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    if brightness < MIN_REC_BRIGHTNESS or brightness > MAX_REC_BRIGHTNESS:
        return False
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return sharpness >= MIN_REC_SHARPNESS

def get_embedding(face_crop):
    if not _rec_model:
        return None
    face_crop = _normalize_lighting(face_crop)
    blob = preprocess(face_crop, _rec_h, _rec_w)
    out = _rec_model([blob])[_rec_model.output(0)].flatten()
    return out / (np.linalg.norm(out) + 1e-9)

def _is_live_face(face_crop):
    """
    anti-spoof-mn3 output: [real_prob, spoof_prob]
    Docs: class 0 = real, class 1 = spoof.
    """
    if not _spoof_model:
        # Security-first: if liveness model is unavailable, reject.
        return False
    if face_crop is None or face_crop.size == 0:
        return False
    try:
        # anti-spoof-mn3 converted/ONNX path expects BGR, 1x3x128x128.
        resized = cv2.resize(face_crop, (_spoof_w, _spoof_h), interpolation=cv2.INTER_AREA)
        blob = np.transpose(resized, (2, 0, 1))[None].astype(np.float32, copy=False)
        # Recommended normalization from model card.
        mean = np.array([151.2405, 119.5950, 107.8395], dtype=np.float32).reshape(1, 3, 1, 1)
        scale = np.array([63.0105, 56.4570, 55.0035], dtype=np.float32).reshape(1, 3, 1, 1)
        blob = (blob - mean) / scale
        out = _spoof_model([blob])[_spoof_model.output(0)].flatten().astype(np.float32, copy=False)
        if out.size < 2:
            return False
        scores = out[:2]
        # Some exports emit logits; normalize to probabilities when needed.
        if np.any(scores < 0.0) or abs(float(scores.sum()) - 1.0) > 0.1:
            exps = np.exp(scores - np.max(scores))
            scores = exps / (np.sum(exps) + 1e-9)
        real_prob = float(scores[0])
        spoof_prob = float(scores[1])
        return real_prob >= LIVENESS_REAL_THRESHOLD and real_prob > spoof_prob
    except Exception:
        return False

def verify_face(school_id, frame, gallery, return_box=False):
    if not _det_model or not _det_req or not _rec_model:
        return False, "Recognition model unavailable", None
    if school_id not in gallery:
        return False, "No Facial Data", None
    frame_proc = cv2.resize(frame, (PROCESS_WIDTH, PROCESS_HEIGHT))
    blob = preprocess(frame_proc, _det_h, _det_w)
    _det_req.infer({_det_model.input(0).any_name: blob})
    detections = _det_req.get_output_tensor(0).data

    h, w, _ = frame_proc.shape
    faces = [
        (
            float(det[2]),
            int(det[3] * w),
            int(det[4] * h),
            int(det[5] * w),
            int(det[6] * h)
        )
        for det in detections[0][0]
        if det[2] > CONF_THRESHOLD
    ]

    if not faces:
        return False, "No Face Detected", None

    _, xmin, ymin, xmax, ymax = max(
        faces,
        key=lambda f: f[0] * ((f[3] - f[1]) * (f[4] - f[2]))
    )

    scale_x = frame.shape[1] / PROCESS_WIDTH
    scale_y = frame.shape[0] / PROCESS_HEIGHT
    x1, y1, x2, y2 = map(int, [xmin * scale_x, ymin * scale_y, xmax * scale_x, ymax * scale_y])
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)

    face_crop = frame[y1:y2, x1:x2]
    if face_crop.size == 0:
        return False, "Invalid Crop", (x1, y1, x2, y2)
    if not _face_quality_ok(face_crop):
        return False, "Unrecognized", (x1, y1, x2, y2)
    if not _is_live_face(face_crop):
        return False, "Unrecognized", (x1, y1, x2, y2)

    emb = get_embedding(face_crop)
    if emb is None:
        return False, "Embedding Failed", (x1, y1, x2, y2)

    sims = [(1 - cosine(emb, g["embedding"]), sid) for sid, g in gallery.items()]
    sims.sort(reverse=True, key=lambda x: x[0])
    best_sim, best_id = sims[0]
    ok = best_sim >= SIM_THRESHOLD

    if ok and best_id == school_id:
        return True, best_id, (x1, y1, x2, y2) if return_box else None
    elif ok:
        return False, "Unrecognized", (x1, y1, x2, y2) if return_box else None
    return False, "Unrecognized", (x1, y1, x2, y2) if return_box else None
