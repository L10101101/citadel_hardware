from PyQt6.QtCore import QThread, pyqtSignal
import cv2
import numpy as np
from time import time
from face_enrollment import extract_embedding, save_to_db, open_camera, get_face, STILL_DURATION

class FaceEnrollWorker(QThread):
    finished = pyqtSignal(bool, str)
    frameReady = pyqtSignal(object)

    def __init__(self, student_no, label_widget=None):
        super().__init__()
        self.student_no = student_no
        self.label_widget = label_widget
        self._running = True
        self.cap = None

    def run(self):
        try:
            self.cap = open_camera()
            last_box, face_box = None, None
            still_start, face_crop = None, None
            frame_count = 0
            DETECT_INTERVAL = 3
            last_detect_time = 0

            while self._running:
                ret, frame = self.cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)
                h, w, _ = frame.shape
                side = min(h, w)
                start_x = (w - side) // 2
                start_y = (h - side) // 2
                frame = frame[start_y:start_y + side, start_x:start_x + side]
                frame = cv2.resize(frame, (600, 600))
                frame_count += 1
                now = time()

                if frame_count % DETECT_INTERVAL == 0 or face_box is None:
                    small = cv2.resize(frame, (1280, 720))
                    detected = get_face(small)
                    if detected:
                        sx, sy = frame.shape[1] / 1280, frame.shape[0] / 720
                        face_box = [int(detected[0] * sx), int(detected[1] * sy),
                                    int(detected[2] * sx), int(detected[3] * sy)]
                        last_detect_time = now
                    elif now - last_detect_time > 0.5:
                        face_box = None

                if face_box:
                    x1, y1, x2, y2 = face_box
                    if last_box is not None:
                        movement = np.linalg.norm(np.subtract(face_box, last_box))
                        if movement < 25:
                            if still_start is None:
                                still_start = now
                            elif now - still_start >= STILL_DURATION:
                                face_crop = frame[y1:y2, x1:x2]
                                break
                        else:
                            still_start = None
                    last_box = face_box

                    text = f"Capturing in {max(0, STILL_DURATION - (now - still_start)):.1f}s" \
                        if still_start else "Hold Still"
                    cv2.putText(frame, text, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                else:
                    cv2.putText(frame, "No Face Detected", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                    still_start, last_box = None, None

                self.frameReady.emit(frame)
                self.msleep(5)

        except Exception as e:
            self.finished.emit(False, f"Error: {e}")

        finally:
            if self.cap:
                self.cap.release()
                self.cap = None

            if face_crop is not None:
                try:
                    emb = extract_embedding(face_crop)
                    save_to_db(self.student_no, emb)
                    self.finished.emit(True, "Success")
                except Exception as e:
                    self.finished.emit(False, f"Error {e}")
            elif self._running:
                self.finished.emit(False, "Enrollment Cancelled")

    def stop(self):
        self._running = False
        if self.cap:
            self.cap.release()
            self.cap = None
