import cv2
import psycopg2
import numpy as np
import os
from openvino.runtime import Core
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from utils import get_connection


load_dotenv()
FERNET_KEY = os.getenv("CRYPT_FERNET_KEY")
cipher = Fernet(FERNET_KEY)
CONF_THRESHOLD = 0.8
STILL_DURATION = 2.0
CAMERA_INDEX = 0
CAMERA_WIDTH = 3840
CAMERA_HEIGHT = 2160
FPS = 30


DET_MODEL = "./models/intel/face-detection-adas-0001/FP16/face-detection-adas-0001.xml"
REC_MODEL = "./models/intel/face-reidentification-retail-0095/FP16/face-reidentification-retail-0095.xml"
ie = Core()
det_model = ie.compile_model(ie.read_model(DET_MODEL), "GPU")
rec_model = ie.compile_model(ie.read_model(REC_MODEL), "GPU")
det_output = det_model.output(0)
rec_output = rec_model.output(0)


def open_camera():
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {CAMERA_INDEX}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)
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
    return max(faces, key=lambda f: f[4])[:4]


def extract_embedding(face_crop):
    resized = cv2.resize(face_crop, (128, 128))
    blob = np.expand_dims(resized.transpose(2, 0, 1), axis=0)
    emb = rec_model([blob])[rec_output].flatten().astype(np.float32)
    return emb / (np.linalg.norm(emb) + 1e-9)


def save_to_db(student_no, emb):
    emb_bytes = emb.tobytes()
    encrypted = cipher.encrypt(emb_bytes)
    conn = get_connection()
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

    if not success:
        raise ValueError(f"{student_no} not found")
