from PyQt6.QtCore import QThread, pyqtSignal
import cv2
from time import time
import numpy as np
from face_enrollment import (
    extract_embedding,
    save_to_db,
    open_camera,
    get_face,
    STILL_DURATION
)

class FaceEnrollWorker(QThread):
    finished = pyqtSignal(bool, str)
    frameReady = pyqtSignal(object)

    def __init__(self, student_no, label_widget=None):
        super().__init__()
        self.student_no = student_no
        self.label_widget = label_widget
        self._running = True
        self.cap = None  # <-- keep reference to camera

    def run(self):
        try:
            # Open camera and keep reference for cleanup
            self.cap = open_camera()
            last_box = None
            still_start = None
            face_crop = None

            while self._running:
                if self.cap is None:
                    break

                ret, frame = self.cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)
                face_box = get_face(frame)
                now = time()

                if face_box:
                    x1, y1, x2, y2 = face_box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    # Detect minimal motion
                    if last_box is not None:
                        dx = abs(x1 - last_box[0]) + abs(x2 - last_box[2])
                        dy = abs(y1 - last_box[1]) + abs(y2 - last_box[3])
                        movement = dx + dy

                        if movement < 50:
                            if still_start is None:
                                still_start = now
                            elif now - still_start >= STILL_DURATION:
                                face_crop = frame[y1:y2, x1:x2]
                                break
                        else:
                            still_start = None
                    else:
                        still_start = None

                    last_box = face_box

                    # Overlay text
                    if still_start:
                        elapsed = now - still_start
                        remaining = max(0, STILL_DURATION - elapsed)
                        cv2.putText(frame, f"Capturing in {remaining:.1f}s",
                                    (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX,
                                    0.7, (0, 255, 255), 2)
                    else:
                        cv2.putText(frame, "Hold still...",
                                    (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX,
                                    0.7, (255, 255, 0), 2)
                else:
                    cv2.putText(frame, "No face detected",
                                (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (0, 0, 255), 2)
                    still_start = None
                    last_box = None

                self.frameReady.emit(frame)

        except Exception as e:
            self.finished.emit(False, f"Error: {e}")

        finally:
            # --- Safe cleanup ---
            if self.cap:
                self.cap.release()
                self.cap = None

            # Process face crop if captured
            if face_crop is not None:
                try:
                    emb = extract_embedding(face_crop)
                    save_to_db(self.student_no, emb)
                    self.finished.emit(True, "Facial enrollment successful.")
                except Exception as e:
                    self.finished.emit(False, f"Error saving data: {e}")
            elif self._running:
                # Finished without a face crop
                self.finished.emit(False, "Enrollment cancelled or no face captured.")

    def stop(self):
        """Stop the thread and release camera safely."""
        self._running = False
        if self.cap:
            self.cap.release()
            self.cap = None
