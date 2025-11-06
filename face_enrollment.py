import cv2
import psycopg2
import numpy as np
import os
from time import time
from openvino.runtime import Core
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
CONF_THRESHOLD = 0.5
STILL_DURATION = 3.0  # seconds
CAMERA_INDEX = 0
CAMERA_WIDTH = 3840
CAMERA_HEIGHT = 2160
DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080
FPS = 30
# ----------------------------

ie = Core()
det_model = ie.compile_model(ie.read_model(DET_MODEL), "GPU")
rec_model = ie.compile_model(ie.read_model(REC_MODEL), "GPU")
det_output = det_model.output(0)
rec_output = rec_model.output(0)


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def open_camera():
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"❌ Cannot open camera index {CAMERA_INDEX}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    return cap


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
        SET facial_recognition_data = %s
        WHERE student_no = %s
    """, (psycopg2.Binary(encrypted), student_no))
    if cur.rowcount == 0:
        print(f"❌ Student {student_no} not found in database.")
    else:
        print(f"✅ Updated encrypted facial recognition data for {student_no}")
    conn.commit()
    cur.close()
    conn.close()


def capture_face_auto():
    cap = open_camera()
    cv2.namedWindow("Face Enrollment", cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty("Face Enrollment", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    last_box = None
    still_start = None
    captured = False
    face_crop = None

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.flip(frame, 1)
        face_box = get_face(frame)
        if face_box:
            x1, y1, x2, y2 = face_box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 7)

            if last_box is not None:
                dx = abs(x1 - last_box[0]) + abs(x2 - last_box[2])
                dy = abs(y1 - last_box[1]) + abs(y2 - last_box[3])
                if dx + dy < 15:
                    if still_start is None:
                        still_start = time()
                    elif time() - still_start >= STILL_DURATION:
                        face_crop = frame[y1:y2, x1:x2]
                        captured = True
                        break
                else:
                    still_start = None
            last_box = face_box

            if still_start:
                remaining = max(0, STILL_DURATION - (time() - still_start))
                cv2.putText(frame, f"Capturing in {remaining:.1f}s",
                            (x1, y1 - 20), cv2.FONT_HERSHEY_SIMPLEX,
                            2.0, (0, 255, 255), 4)
            else:
                cv2.putText(frame, "Hold still...",
                            (x1, y1 - 20), cv2.FONT_HERSHEY_SIMPLEX,
                            2.0, (255, 255, 0), 4)
        else:
            cv2.putText(frame, "No face detected",
                        (100, 150), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (0, 0, 255), 2)
            still_start = None
            last_box = None

        disp_frame = cv2.resize(frame, (DISPLAY_WIDTH, DISPLAY_HEIGHT))
        cv2.imshow("Face Enrollment", disp_frame)

        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()
    if captured:
        return face_crop
    raise RuntimeError("No capture performed.")


def main():
    student_no = input("Enter Student No: ").strip()

    try:
        face_crop = capture_face_auto()
        emb = extract_embedding(face_crop)
        save_to_db(student_no, emb)
    except Exception as e:
        print("❌ Error:", e)


if __name__ == "__main__":
    main()
