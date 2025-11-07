import os
import cv2
import numpy as np
import psycopg2
from openvino.runtime import Core
from scipy.spatial.distance import cosine
from cryptography.fernet import Fernet
from dotenv import load_dotenv


DB_CONFIG = {
    "dbname": "citadel_db",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 5432
}


load_dotenv()
FERNET_KEY = os.getenv("CRYPT_FERNET_KEY")
if not FERNET_KEY:
    raise ValueError("Missing FERNET_KEY in .env file")
fernet = Fernet(FERNET_KEY.encode())


OPENVINO_LIBS = r".\venv\Lib\site-packages\openvino\libs"
os.environ["PATH"] = OPENVINO_LIBS + os.pathsep + os.environ.get("PATH", "")


PROCESS_WIDTH, PROCESS_HEIGHT = 960, 540
CONF_THRESHOLD = 0.75
SIM_THRESHOLD = 0.75


DET_MODEL = "./models/intel/face-detection-adas-0001/FP16/face-detection-adas-0001.xml"
REC_MODEL = "./models/intel/face-reidentification-retail-0095/FP16/face-reidentification-retail-0095.xml"


_ie = Core()
def _load_model(model_path, device="GPU"):
    try:
        model = _ie.compile_model(_ie.read_model(model_path), device)
        return model
    except Exception:
        return None

_det_model = _load_model(DET_MODEL)
_rec_model = _load_model(REC_MODEL)

_det_h, _det_w = _det_model.input(0).shape[2:] if _det_model else (0, 0)
_rec_h, _rec_w = _rec_model.input(0).shape[2:] if _rec_model else (0, 0)

_det_req = _det_model.create_infer_request() if _det_model else None
_gallery_cache = None


def load_gallery(force_reload=False):
    global _gallery_cache

    if _gallery_cache is not None and not force_reload:
        return _gallery_cache

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT student_no, facial_recognition_data FROM students")
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return {}

    gallery = {}
    for sid, blob in rows:

        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        elif isinstance(blob, str):
            try:
                blob = bytes.fromhex(blob)
            except ValueError:
                try:
                    import base64
                    blob = base64.b64decode(blob)
                except Exception:
                    blob = blob.encode("utf-8")

        try:
            decrypted = fernet.decrypt(blob)
            embedding = np.frombuffer(decrypted, np.float32)
            if embedding.size == 0:
                continue

            gallery[sid] = {"embedding": embedding}
        except Exception as e:
            print(f"{sid}: {e}")

    _gallery_cache = gallery
    return _gallery_cache


def reset_models():
    global _det_model, _rec_model, _det_req, _gallery_cache

    _gallery_cache = None
    try:
        _det_model = _load_model(DET_MODEL)
        _rec_model = _load_model(REC_MODEL)
        _det_req = _det_model.create_infer_request() if _det_model else None
    except Exception as e:
        print(f"Failed To R {e}")


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


def verify_face(school_id, frame, gallery, return_box=False):
    if school_id not in gallery:
        return False, "Not Found", None

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
        for det in detections[0][0] if det[2] > CONF_THRESHOLD
    ]

    if not faces:
        return False, "No Face Detected", None

    _, xmin, ymin, xmax, ymax = max(faces, key=lambda f: f[0])
    scale_x = frame.shape[1] / PROCESS_WIDTH
    scale_y = frame.shape[0] / PROCESS_HEIGHT

    x1, y1, x2, y2 = map(int, [
        xmin * scale_x, ymin * scale_y, xmax * scale_x, ymax * scale_y
    ])
    x1, y1 = max(x1, 0), max(y1, 0)
    x2, y2 = min(x2, frame.shape[1]), min(y2, frame.shape[0])

    face_crop = frame[y1:y2, x1:x2]
    if face_crop.size == 0:
        return False, "Invalid Crop", (x1, y1, x2, y2)

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
        return False, "Different ID", (x1, y1, x2, y2) if return_box else None
    return False, "Unrecognized", (x1, y1, x2, y2) if return_box else None