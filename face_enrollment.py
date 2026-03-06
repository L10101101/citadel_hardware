import cv2
import psycopg2
import numpy as np
import logging
import time

from openvino.runtime import Core
from cryptography.fernet import Fernet
from db_utils import get_connection
from config_store import get_fernet_key
from utils import resource_path

logger = logging.getLogger(__name__)

CONF_THRESHOLD = 0.8
STILL_DURATION = 2.0

CAMERA_INDEX = 0
CAMERA_WIDTH = 3840
CAMERA_HEIGHT = 2160
FPS = 12

MIN_FACE_SIZE = 120
MIN_BRIGHTNESS = 45.0
MAX_BRIGHTNESS = 220.0
MIN_SHARPNESS = 70.0
CLOUD_ENROLL_MAX_RETRIES = 3
CLOUD_ENROLL_BACKOFF_SEC = 0.5

DET_MODEL = resource_path("models/intel/face-detection-adas-0001/FP16/face-detection-adas-0001.xml")
REC_MODEL = resource_path("models/intel/face-reidentification-retail-0095/FP16/face-reidentification-retail-0095.xml")
ie = Core()


def _compile_with_fallback(model_path, preferred=("GPU", "CPU")):
    model = ie.read_model(model_path)

    for device in preferred:
        try:
            return ie.compile_model(model, device)
        except Exception:
            continue
    raise RuntimeError(
        "Failed to compile model: {}. Tried devices: {}".format(model_path, ", ".join(preferred))
    )

det_model = _compile_with_fallback(DET_MODEL)
rec_model = _compile_with_fallback(REC_MODEL)
det_output = det_model.output(0)
rec_output = rec_model.output(0)


def open_camera():
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {CAMERA_INDEX}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    try:
        cap.set(cv2.CAP_PROP_AUTO_WB, 1)
    except Exception:
        pass
    try:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
    except Exception:
        pass
    return cap


def get_center_crop(frame):
    h, w, _ = frame.shape
    crop_size = min(h, w)
    x_start = (w - crop_size) // 2
    y_start = (h - crop_size) // 2
    cropped = frame[y_start:y_start + crop_size, x_start:x_start + crop_size]
    return cropped


def get_face(frame):
    h, w = frame.shape[:2]
    blob = cv2.resize(frame, (672, 384)).transpose(2, 0, 1)[None].astype(np.float32)
    det_result = det_model([blob])[det_output][0][0]

    faces = [
        (int(det[3] * w), int(det[4] * h), int(det[5] * w), int(det[6] * h), float(det[2]))
        for det in det_result if det[2] > CONF_THRESHOLD
    ]

    if not faces:
        return None

    best_face = max(faces, key=lambda f: f[4] * ((f[2] - f[0]) * (f[3] - f[1])))
    return best_face[:4]


def _normalize_lighting(face_crop):
    lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv2.merge([l, a, b])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def face_quality_metrics(face_crop):
    if face_crop is None or face_crop.size == 0:
        return {"ok": False, "reason": "invalid"}
    h, w = face_crop.shape[:2]
    if min(h, w) < MIN_FACE_SIZE:
        return {"ok": False, "reason": "small_face"}
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < MIN_BRIGHTNESS:
        return {"ok": False, "reason": "too_dark", "brightness": brightness, "sharpness": sharpness}
    if brightness > MAX_BRIGHTNESS:
        return {"ok": False, "reason": "too_bright", "brightness": brightness, "sharpness": sharpness}
    if sharpness < MIN_SHARPNESS:
        return {"ok": False, "reason": "blurry", "brightness": brightness, "sharpness": sharpness}
    return {"ok": True, "reason": "ok", "brightness": brightness, "sharpness": sharpness}


def extract_embedding(face_crop):
    face_crop = _normalize_lighting(face_crop)
    resized = cv2.resize(face_crop, (128, 128))
    blob = np.expand_dims(resized.transpose(2, 0, 1), axis=0)
    emb = rec_model([blob])[rec_output].flatten().astype(np.float32)
    return emb / (np.linalg.norm(emb) + 1e-9)


def save_to_cloud(student_no, emb):
    key = get_fernet_key()
    if not key:
        raise ValueError("Fernet key not configured.")
    cipher = Fernet(key.encode() if isinstance(key, str) else key)
    emb_bytes = emb.tobytes()
    encrypted = cipher.encrypt(emb_bytes)

    last_error = None
    for attempt in range(1, CLOUD_ENROLL_MAX_RETRIES + 1):
        conn = None
        cur = None
        try:
            conn, source = get_connection("cloud")
            cur = conn.cursor()
            cur.execute("""
                UPDATE students
                SET facial_recognition_data = %s,
                    has_facial_recognition = TRUE
                WHERE student_no = %s
            """, (psycopg2.Binary(encrypted), student_no))
            conn.commit()
            success = cur.rowcount > 0
            if success:
                logger.info("Saved face embedding to cloud for student %s", student_no)
                return
            logger.warning("Student not found in cloud while saving face embedding: %s", student_no)
            raise ValueError(f"{student_no} Not Found")
        except ValueError:
            raise
        except Exception as e:
            last_error = e
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if attempt < CLOUD_ENROLL_MAX_RETRIES:
                wait_sec = CLOUD_ENROLL_BACKOFF_SEC * (2 ** (attempt - 1))
                logger.warning(
                    "Cloud face enrollment failed attempt %d/%d for student %s: %s; retrying in %.1fs",
                    attempt,
                    CLOUD_ENROLL_MAX_RETRIES,
                    student_no,
                    e,
                    wait_sec,
                )
                time.sleep(wait_sec)
            else:
                logger.warning(
                    "Cloud face enrollment failed attempt %d/%d for student %s: %s",
                    attempt,
                    CLOUD_ENROLL_MAX_RETRIES,
                    student_no,
                    e,
                )
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
    raise RuntimeError(f"Cloud enrollment failed after {CLOUD_ENROLL_MAX_RETRIES} attempt(s): {last_error}")


def save_to_db(student_no, emb):
    key = get_fernet_key()
    if not key:
        raise ValueError("Fernet key not configured.")
    cipher = Fernet(key.encode() if isinstance(key, str) else key)
    emb_bytes = emb.tobytes()
    encrypted = cipher.encrypt(emb_bytes)

    conn, source = get_connection("local")
    cur = conn.cursor()

    cur.execute("""
        UPDATE students
        SET facial_recognition_data = %s,
            has_facial_recognition = TRUE
        WHERE student_no = %s
    """, (psycopg2.Binary(encrypted), student_no))
    conn.commit()

    success = cur.rowcount > 0
    cur.close()
    conn.close()

    if success:
        logger.info("Saved face embedding locally for student %s", student_no)
    else:
        logger.warning("Student not found in local DB while saving face embedding: %s", student_no)
        raise ValueError(f"{student_no} Not Found")

