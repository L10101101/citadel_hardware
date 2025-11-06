import cv2, os
import numpy as np
from openvino.runtime import Core
from scipy.spatial.distance import cosine
import psycopg2
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

# ---------- CONFIG ----------
DB_CONFIG = {
    "dbname": "citadel_db",
    "user": "postgres",
    "password": "postgres",
    "host": "127.0.0.1",
    "port": 5432
}

FERNET_KEY = os.getenv("CRYPT_FERNET_KEY")
cipher = Fernet(FERNET_KEY)

DET_MODEL = "./models/intel/face-detection-adas-0001/FP16/face-detection-adas-0001.xml"
REC_MODEL = "./models/intel/face-reidentification-retail-0095/FP16/face-reidentification-retail-0095.xml"

PROCESS_WIDTH, PROCESS_HEIGHT = 960, 540
CONF_THRESHOLD = 0.75
SIM_THRESHOLD = 0.75

# OpenVINO
_ie = Core()

def _load_model(model_path, device="GPU"):
    try:
        return _ie.compile_model(_ie.read_model(model_path), device)
    except Exception:
        return None

_det_model = _load_model(DET_MODEL)
_rec_model = _load_model(REC_MODEL)

_det_h, _det_w = _det_model.input(0).shape[2:] if _det_model else (0, 0)
_rec_h, _rec_w = _rec_model.input(0).shape[2:] if _rec_model else (0, 0)
_det_req = _det_model.create_infer_request() if _det_model else None

# ----------------- Database -----------------
def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def load_gallery(force_reload=False):
    """Load all encrypted embeddings from students table and decrypt them."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT student_no, facial_recognition_data FROM students WHERE facial_recognition_data IS NOT NULL")
    rows = cur.fetchall()
    conn.close()

    gallery = {}
    for sid, enc_blob in rows:
        try:
            emb_bytes = cipher.decrypt(enc_blob.tobytes())
            emb = np.frombuffer(emb_bytes, dtype=np.float32)
            gallery[sid] = {"embedding": emb}
        except Exception:
            continue
    return gallery

# ----------------- Image Preprocessing -----------------
def preprocess(img, h, w, rgb=False):
    resized = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    if rgb:
        resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    blob = np.transpose(resized, (2, 0, 1))[None].astype(np.float32, copy=False)
    return blob

def get_embedding(face_crop):
    if not _rec_model:
        return None
    blob = preprocess(face_crop, _rec_h, _rec_w)
    out = _rec_model([blob])[_rec_model.output(0)].flatten()
    return out / (np.linalg.norm(out) + 1e-9)

# ----------------- Face Verification -----------------
def verify_face(school_id, frame, gallery, return_box=False):
    if school_id not in gallery:
        return False, "Not Found", None

    frame_proc = cv2.resize(frame, (PROCESS_WIDTH, PROCESS_HEIGHT))
    blob = preprocess(frame_proc, _det_h, _det_w)
    _det_req.infer({ _det_model.input(0).any_name: blob })
    detections = _det_req.get_output_tensor(0).data

    h, w, _ = frame_proc.shape
    faces = [
        (float(det[2]), int(det[3]*w), int(det[4]*h), int(det[5]*w), int(det[6]*h))
        for det in detections[0][0] if det[2] > CONF_THRESHOLD
    ]
    if not faces:
        return False, "No face detected", None

    _, xmin, ymin, xmax, ymax = max(faces, key=lambda f: f[0])
    scale_x = frame.shape[1] / PROCESS_WIDTH
    scale_y = frame.shape[0] / PROCESS_HEIGHT
    x1, y1, x2, y2 = map(int, [xmin * scale_x, ymin * scale_y, xmax * scale_x, ymax * scale_y])
    x1, y1 = max(x1, 0), max(y1, 0)
    x2, y2 = min(x2, frame.shape[1]), min(y2, frame.shape[0])

    face_crop = frame[y1:y2, x1:x2]
    if face_crop.size == 0:
        return False, "Invalid crop", (x1, y1, x2, y2)

    emb = get_embedding(face_crop)
    if emb is None:
        return False, "Embedding failed", (x1, y1, x2, y2)

    sims = [(1 - cosine(emb, g["embedding"]), sid) for sid, g in gallery.items()]
    sims.sort(reverse=True, key=lambda x: x[0])
    best_sim, best_id = sims[0]
    ok = best_sim >= SIM_THRESHOLD

    if ok and best_id == school_id:
        return True, best_id, (x1, y1, x2, y2) if return_box else None
    elif ok:
        return False, f"Different ID", (x1, y1, x2, y2) if return_box else None
    return False, f"Unrecognized", (x1, y1, x2, y2) if return_box else None
