import os
import sys
import logging
import time
import cv2
import numpy as np

from openvino.runtime import Core
from cryptography.fernet import Fernet
from db_utils import get_connection
from config_store import get_fernet_key, get_app_config
from utils import resource_path

logger = logging.getLogger(__name__)

PROCESS_WIDTH, PROCESS_HEIGHT = 960, 540
CONF_THRESHOLD = 0.75
SIM_THRESHOLD = 0.75

_app_cfg = get_app_config()

VERIFY_SIM_THRESHOLD = float(
    os.environ.get(
        "FACE_VERIFY_SIM_THRESHOLD",
        str(_app_cfg.get("face_verify_sim_threshold", SIM_THRESHOLD)),
    )
)

IDENTIFY_SIM_THRESHOLD = float(
    os.environ.get(
        "FACE_IDENTIFY_SIM_THRESHOLD",
        str(_app_cfg.get("face_identify_sim_threshold", 0.70)),
    )
)

LIVENESS_REAL_THRESHOLD = 0.85
MIN_REC_FACE_SIZE = 90
MIN_REC_BRIGHTNESS = 35.0
MAX_REC_BRIGHTNESS = 230.0
MIN_REC_SHARPNESS = 45.0
EMBEDDING_DIM = 256

PERF_LOG_EVERY = max(0, int(os.environ.get("FACE_PERF_LOG_EVERY", "0")))
GALLERY_TTL_SECONDS = max(0, int(os.environ.get("FACE_GALLERY_TTL_SECONDS", "300")))

DET_MODEL = resource_path("models/intel/face-detection-adas-0001/FP16/face-detection-adas-0001.xml")
REC_MODEL = resource_path("models/intel/face-reidentification-retail-0095/FP16/face-reidentification-retail-0095.xml")
SPOOF_MODEL = resource_path("models/intel/anti-spoof-mn3/anti-spoof-mn3.onnx")
_ie = Core()
_model_file_errors = []


def _load_model(model_path, preferred=("GPU", "CPU")):
    if not os.path.exists(model_path):
        logger.error("Model file missing: %s", model_path)
        return None
    for device in preferred:
        try:
            return _ie.compile_model(_ie.read_model(model_path), device)
        except Exception:
            continue
    logger.error("Failed to compile model on available devices: %s", model_path)
    return None

_det_model = _load_model(DET_MODEL)
_rec_model = _load_model(REC_MODEL)
_spoof_model = _load_model(SPOOF_MODEL)

for _path in (DET_MODEL, REC_MODEL, SPOOF_MODEL):
    if not os.path.exists(_path):
        _model_file_errors.append(_path)

_det_h, _det_w = _det_model.input(0).shape[2:] if _det_model else (0, 0)
_rec_h, _rec_w = _rec_model.input(0).shape[2:] if _rec_model else (0, 0)
_spoof_h, _spoof_w = _spoof_model.input(0).shape[2:] if _spoof_model else (0, 0)

_gallery_cache = None
_gallery_embeddings = None
_gallery_student_nos = None
_gallery_loaded_at = 0.0
_fernet_instance = None
_perf_counter = 0


def _similarity_threshold(mode: str = "verify") -> float:
    if mode == "identify":
        return IDENTIFY_SIM_THRESHOLD
    return VERIFY_SIM_THRESHOLD


def _get_fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    key = get_fernet_key()
    if not key:
        raise ValueError("Fernet key not configured.")
    _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet_instance


def _get_openvino_libs():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "openvino_libs")
    return os.path.join(os.path.dirname(__file__), "venv", "Lib", "site-packages", "openvino", "libs")

_openvino_libs = _get_openvino_libs()
if os.path.exists(_openvino_libs):
    os.environ["PATH"] = _openvino_libs + os.pathsep + os.environ.get("PATH", "")


def load_gallery(force_reload=False):
    global _gallery_cache, _gallery_embeddings, _gallery_student_nos, _gallery_loaded_at
    now = time.monotonic()
    stale = GALLERY_TTL_SECONDS > 0 and (now - _gallery_loaded_at) >= GALLERY_TTL_SECONDS
    if _gallery_cache is not None and not force_reload and not stale:
        return _gallery_cache
    conn = None
    cur = None
    rows = []
    query_ok = False

    try:
        conn, source = get_connection("local")
        cur = conn.cursor()
        cur.execute("""
            SELECT student_no, facial_recognition_data
            FROM students
            WHERE has_facial_recognition = TRUE
        """)
        rows = cur.fetchall()
        query_ok = True
    except Exception:
        logger.exception("Failed to load facial gallery from database")
        if _gallery_cache is not None:
            logger.warning("Using stale facial gallery cache due to DB read failure")
            return _gallery_cache
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    gallery = {}
    embeddings = []
    student_nos = []
    fernet = _get_fernet()
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
            decrypted = fernet.decrypt(blob)
            embedding = np.frombuffer(decrypted, dtype=np.float32)
            if embedding.size != EMBEDDING_DIM:
                logger.warning(
                    "Skipping student %s: invalid embedding size (expected=%d, got=%d)",
                    sid,
                    EMBEDDING_DIM,
                    embedding.size,
                )
                continue
            if not np.isfinite(embedding).all():
                logger.warning("Skipping student %s: embedding has non-finite values", sid)
                continue
            emb_norm = embedding / (np.linalg.norm(embedding) + 1e-9)
            gallery[sid] = {"embedding": emb_norm}
            embeddings.append(emb_norm)
            student_nos.append(sid)
        except Exception as e:
            logger.warning("Failed to decrypt facial data for student %s: %s", sid, e)

    if query_ok:
        _gallery_cache = gallery
        _gallery_embeddings = np.stack(embeddings, axis=0).astype(np.float32) if embeddings else None
        _gallery_student_nos = student_nos
        _gallery_loaded_at = now
    return _gallery_cache


def reset_models():
    global _det_model, _rec_model, _spoof_model, _gallery_cache, _gallery_embeddings, _gallery_student_nos, _gallery_loaded_at
    _gallery_cache = None
    _gallery_embeddings = None
    _gallery_student_nos = None
    _gallery_loaded_at = 0.0
    try:
        _det_model = _load_model(DET_MODEL)
        _rec_model = _load_model(REC_MODEL)
        _spoof_model = _load_model(SPOOF_MODEL)
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

def _face_quality_check(face_crop):
    if face_crop is None or face_crop.size == 0:
        return False, "Invalid Crop"
    h, w = face_crop.shape[:2]
    if min(h, w) < MIN_REC_FACE_SIZE:
        return False, "Face too small"
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    if brightness < MIN_REC_BRIGHTNESS:
        return False, "Too dark"
    if brightness > MAX_REC_BRIGHTNESS:
        return False, "Too bright"
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if sharpness < MIN_REC_SHARPNESS:
        return False, "Too blurry"
    return True, None


def get_embedding(face_crop):
    if not _rec_model:
        return None
    face_crop = _normalize_lighting(face_crop)
    blob = preprocess(face_crop, _rec_h, _rec_w)
    out = _rec_model([blob])[_rec_model.output(0)].flatten()
    return out / (np.linalg.norm(out) + 1e-9)


def _is_live_face(face_crop):
    if not _spoof_model:
        return False
    if face_crop is None or face_crop.size == 0:
        return False
    try:
        resized = cv2.resize(face_crop, (_spoof_w, _spoof_h), interpolation=cv2.INTER_AREA)
        blob = np.transpose(resized, (2, 0, 1))[None].astype(np.float32, copy=False)
        mean = np.array([151.2405, 119.5950, 107.8395], dtype=np.float32).reshape(1, 3, 1, 1)
        scale = np.array([63.0105, 56.4570, 55.0035], dtype=np.float32).reshape(1, 3, 1, 1)
        blob = (blob - mean) / scale
        out = _spoof_model([blob])[_spoof_model.output(0)].flatten().astype(np.float32, copy=False)
        if out.size < 2:
            return False
        scores = out[:2]
        if np.any(scores < 0.0) or abs(float(scores.sum()) - 1.0) > 0.1:
            exps = np.exp(scores - np.max(scores))
            scores = exps / (np.sum(exps) + 1e-9)
        real_prob = float(scores[0])
        spoof_prob = float(scores[1])
        return real_prob >= LIVENESS_REAL_THRESHOLD and real_prob > spoof_prob
    except Exception:
        return False


def verify_face(school_id, frame, gallery, return_box=False):
    global _perf_counter
    if not _det_model or not _rec_model:
        return False, "Recognition model unavailable", None
    if not _spoof_model:
        return False, "Liveness model unavailable", None
    if school_id not in gallery:
        return False, "No Facial Data", None
    perf_enabled = PERF_LOG_EVERY > 0
    if perf_enabled:
        t0 = cv2.getTickCount()
    frame_proc = cv2.resize(frame, (PROCESS_WIDTH, PROCESS_HEIGHT))
    blob = preprocess(frame_proc, _det_h, _det_w)
    det_req = _det_model.create_infer_request()
    det_req.infer({_det_model.input(0).any_name: blob})
    detections = det_req.get_output_tensor(0).data
    if perf_enabled:
        t_detect = cv2.getTickCount()

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
    quality_ok, quality_msg = _face_quality_check(face_crop)
    if not quality_ok:
        return False, quality_msg or "Unrecognized", (x1, y1, x2, y2)
    if not _is_live_face(face_crop):
        return False, "Unrecognized", (x1, y1, x2, y2)
    if perf_enabled:
        t_live = cv2.getTickCount()

    emb = get_embedding(face_crop)
    if emb is None:
        return False, "Embedding Failed", (x1, y1, x2, y2)
    if perf_enabled:
        t_embed = cv2.getTickCount()

    if _gallery_embeddings is None or not _gallery_student_nos:
        return False, "No Facial Data", (x1, y1, x2, y2) if return_box else None
    sims = np.dot(_gallery_embeddings, emb)
    best_idx = int(np.argmax(sims))
    best_sim = float(sims[best_idx])
    best_id = _gallery_student_nos[best_idx]
    if perf_enabled:
        t_match = cv2.getTickCount()
        _perf_counter += 1
        if _perf_counter % PERF_LOG_EVERY == 0:
            freq = cv2.getTickFrequency()
            detect_ms = (t_detect - t0) * 1000.0 / freq
            live_ms = (t_live - t_detect) * 1000.0 / freq
            embed_ms = (t_embed - t_live) * 1000.0 / freq
            match_ms = (t_match - t_embed) * 1000.0 / freq
            total_ms = (t_match - t0) * 1000.0 / freq
            logger.info(
                "face_perf detect=%.1fms live=%.1fms embed=%.1fms match=%.2fms total=%.1fms",
                detect_ms,
                live_ms,
                embed_ms,
                match_ms,
                total_ms,
            )
    ok = best_sim >= _similarity_threshold("verify")

    if ok and best_id == school_id:
        return True, best_id, (x1, y1, x2, y2) if return_box else None
    elif ok:
        return False, "Unrecognized", (x1, y1, x2, y2) if return_box else None
    return False, "Unrecognized", (x1, y1, x2, y2) if return_box else None


def get_model_health():
    if _model_file_errors:
        return False, f"Missing model files: {len(_model_file_errors)}"
    if not _det_model or not _rec_model:
        return False, "Recognition model unavailable"
    if not _spoof_model:
        return False, "Liveness model unavailable"
    return True, "ok"
