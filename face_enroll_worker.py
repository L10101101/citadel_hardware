import cv2
import numpy as np

from time import time
from PyQt6.QtCore import QThread, pyqtSignal
from face_enrollment import (
    extract_embedding,
    save_to_cloud,
    open_camera,
    get_face,
    STILL_DURATION,
    face_quality_metrics,
)

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
        face_crop = None
        error_msg = None
        embeddings = []
        try:
            self.cap = open_camera()
            last_box, face_box = None, None
            still_start = None
            sample_start = None
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
                        if movement < 15:
                            if still_start is None:
                                still_start = now
                            elif now - still_start >= STILL_DURATION:
                                if sample_start is None:
                                    sample_start = now
                                crop = frame[y1:y2, x1:x2]
                                metrics = face_quality_metrics(crop)
                                if metrics.get("ok"):
                                    try:
                                        emb = extract_embedding(crop)
                                        if emb is not None and emb.size > 0:
                                            embeddings.append(emb)
                                    except Exception:
                                        pass
                                # Collect a few good samples then average to one embedding.
                                if len(embeddings) >= 5 or (sample_start and now - sample_start >= 2.0):
                                    if embeddings:
                                        face_crop = crop
                                        break
                        else:
                            still_start = None
                            sample_start = None
                    last_box = face_box

                    if still_start and now - still_start >= STILL_DURATION:
                        text = f"Sampling... {len(embeddings)}/5"
                    else:
                        text = f"Capturing in {max(0, STILL_DURATION - (now - still_start)):.1f}s" \
                            if still_start else "Hold Still"
                    cv2.putText(frame, text, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                else:
                    cv2.putText(frame, "No Face Detected", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                    still_start, last_box, sample_start = None, None, None

                self.frameReady.emit(frame)
                self.msleep(5)

        except Exception as e:
            msg = str(e)
            if "Cannot open" in msg:
                error_msg = "Camera not detected"
            else:
                error_msg = f"Error: {e}"

        finally:
            if self.cap:
                self.cap.release()
                self.cap = None

            if error_msg:
                self.finished.emit(False, error_msg)
                return

            if embeddings:
                try:
                    emb = np.mean(np.stack(embeddings, axis=0), axis=0).astype(np.float32)
                    emb = emb / (np.linalg.norm(emb) + 1e-9)
                    save_to_cloud(self.student_no, emb)
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
