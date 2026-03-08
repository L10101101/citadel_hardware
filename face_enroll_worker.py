import cv2
import numpy as np
import os

from time import time
from PyQt6.QtCore import QThread, pyqtSignal
from face_enrollment import (
    extract_embedding,
    save_to_cloud,
    save_to_db,
    open_camera,
    get_face,
    STILL_DURATION,
    face_quality_metrics,
)

ENROLL_AUTO_SHARPEN = os.environ.get("FACE_ENROLL_AUTO_SHARPEN", "1") == "1"
ENROLL_SHARPEN_TRIGGER = float(os.environ.get("FACE_ENROLL_SHARPEN_TRIGGER", "120.0"))
ENROLL_SHARPEN_AMOUNT = float(os.environ.get("FACE_ENROLL_SHARPEN_AMOUNT", "1.2"))
ENROLL_FOCUS_LOCK_SEC = float(os.environ.get("FACE_ENROLL_FOCUS_LOCK_SEC", "0.7"))
ENROLL_FOCUS_MOVE_RESET = float(os.environ.get("FACE_ENROLL_FOCUS_MOVE_RESET", "20.0"))
ENROLL_MIN_FACE_RATIO = float(os.environ.get("FACE_ENROLL_MIN_FACE_RATIO", "0.32"))


def persist_enrollment_embedding(student_no, emb):
    try:
        save_to_cloud(student_no, emb)
        return True, "Success"
    except Exception as e:
        if isinstance(e, ValueError):
            return False, f"Error {e}"
        try:
            save_to_db(student_no, emb)
            return True, "Saved locally (cloud unavailable)"
        except Exception as local_err:
            return False, f"Error {e}; local fallback failed: {local_err}"


def _sharpen_if_needed(face_crop):
    if not ENROLL_AUTO_SHARPEN:
        return face_crop, None
    if face_crop is None or face_crop.size == 0:
        return face_crop, None
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if sharpness >= ENROLL_SHARPEN_TRIGGER:
        return face_crop, None
    blurred = cv2.GaussianBlur(face_crop, (0, 0), 1.2)
    sharpened = cv2.addWeighted(face_crop, 1.0 + ENROLL_SHARPEN_AMOUNT, blurred, -ENROLL_SHARPEN_AMOUNT, 0)
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)
    return sharpened, sharpness


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
        final_embedding = None
        try:
            self.cap = open_camera()
            last_box, face_box = None, None
            still_start = None
            frame_count = 0
            DETECT_INTERVAL = 3
            last_detect_time = 0
            PREVIEW_SIZE = 720
            DETECT_SIZE = 1280
            quality_label = ""
            stable_start = None
            af_locked = False

            while self._running:
                ret, frame = self.cap.read()
                if not ret:
                    continue

                frame = cv2.flip(frame, 1)
                h, w, _ = frame.shape
                side = min(h, w)
                start_x = (w - side) // 2
                start_y = (h - side) // 2
                frame_square = frame[start_y:start_y + side, start_x:start_x + side]
                display_frame = cv2.resize(frame_square, (PREVIEW_SIZE, PREVIEW_SIZE))
                frame_count += 1
                now = time()

                if frame_count % DETECT_INTERVAL == 0 or face_box is None:
                    detect_frame = cv2.resize(frame_square, (DETECT_SIZE, DETECT_SIZE))
                    detected = get_face(detect_frame)
                    if detected:
                        sx, sy = frame_square.shape[1] / DETECT_SIZE, frame_square.shape[0] / DETECT_SIZE
                        x1 = max(0, min(frame_square.shape[1] - 1, int(detected[0] * sx)))
                        y1 = max(0, min(frame_square.shape[0] - 1, int(detected[1] * sy)))
                        x2 = max(0, min(frame_square.shape[1], int(detected[2] * sx)))
                        y2 = max(0, min(frame_square.shape[0], int(detected[3] * sy)))
                        face_box = [x1, y1, x2, y2]
                        last_detect_time = now
                    elif now - last_detect_time > 0.5:
                        face_box = None

                if face_box:
                    x1, y1, x2, y2 = face_box
                    face_w = max(1, x2 - x1)
                    face_h = max(1, y2 - y1)
                    min_side_needed = int(frame_square.shape[0] * ENROLL_MIN_FACE_RATIO)
                    if min(face_w, face_h) < min_side_needed:
                        quality_label = f"Move closer (min {min_side_needed}px)"
                        still_start = None
                        stable_start = None
                        last_box = face_box
                        dx = int(x1 * PREVIEW_SIZE / frame_square.shape[1])
                        dy = int(y1 * PREVIEW_SIZE / frame_square.shape[0])
                        dxx = int(x2 * PREVIEW_SIZE / frame_square.shape[1])
                        dyy = int(y2 * PREVIEW_SIZE / frame_square.shape[0])
                        cv2.rectangle(display_frame, (dx, dy), (dxx, dyy), (0, 140, 255), 2)
                        cv2.putText(
                            display_frame,
                            quality_label,
                            (20, PREVIEW_SIZE - 20),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            (0, 140, 255),
                            2,
                        )
                        self.frameReady.emit(display_frame)
                        self.msleep(5)
                        continue
                    if last_box is not None:
                        movement = np.linalg.norm(np.subtract(face_box, last_box))
                        if movement < ENROLL_FOCUS_MOVE_RESET:
                            if stable_start is None:
                                stable_start = now
                            elif (not af_locked) and (now - stable_start >= ENROLL_FOCUS_LOCK_SEC):
                                try:
                                    self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                                    current_focus = self.cap.get(cv2.CAP_PROP_FOCUS)
                                    if current_focus and current_focus > 0:
                                        self.cap.set(cv2.CAP_PROP_FOCUS, current_focus)
                                    af_locked = True
                                except Exception:
                                    pass
                        else:
                            stable_start = None
                            if af_locked:
                                try:
                                    self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
                                except Exception:
                                    pass
                                af_locked = False
                        if movement < 15:
                            if still_start is None:
                                still_start = now
                            elif now - still_start >= STILL_DURATION:
                                crop = frame_square[y1:y2, x1:x2]
                                eval_crop, pre_sharpness = _sharpen_if_needed(crop)
                                metrics = face_quality_metrics(eval_crop)
                                if pre_sharpness is not None:
                                    metrics["pre_sharpness"] = pre_sharpness
                                    metrics["auto_sharpen"] = True
                                quality_label = (
                                    f"{metrics.get('reason', 'unknown')} "
                                    f"b={metrics.get('brightness', 0.0):.1f} "
                                    f"s={metrics.get('sharpness', 0.0):.1f}"
                                )
                                if metrics.get("ok"):
                                    try:
                                        emb = extract_embedding(eval_crop)
                                        if emb is not None and emb.size > 0:
                                            final_embedding = emb.astype(np.float32)
                                            face_crop = eval_crop
                                            break
                                    except Exception:
                                        pass
                        else:
                            still_start = None
                            stable_start = None
                    last_box = face_box
                    dx = int(x1 * PREVIEW_SIZE / frame_square.shape[1])
                    dy = int(y1 * PREVIEW_SIZE / frame_square.shape[0])
                    dxx = int(x2 * PREVIEW_SIZE / frame_square.shape[1])
                    dyy = int(y2 * PREVIEW_SIZE / frame_square.shape[0])

                    text = (
                        f"Capturing in {max(0, STILL_DURATION - (now - still_start)):.1f}s"
                        if still_start else "Hold Still"
                    )
                    cv2.putText(display_frame, text, (dx, max(20, dy - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
                    cv2.rectangle(display_frame, (dx, dy), (dxx, dyy), (0, 255, 0), 2)
                    if quality_label:
                        cv2.putText(
                            display_frame,
                            quality_label,
                            (20, PREVIEW_SIZE - 20),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            (255, 255, 255),
                            2,
                        )
                else:
                    cv2.putText(display_frame, "No Face Detected", (20, 40),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                    still_start, last_box = None, None
                    stable_start = None
                    quality_label = ""
                    if af_locked:
                        try:
                            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
                        except Exception:
                            pass
                        af_locked = False

                self.frameReady.emit(display_frame)
                self.msleep(5)

        except Exception as e:
            msg = str(e)
            if "Cannot open" in msg:
                error_msg = "Camera not detected"
            else:
                error_msg = f"Error: {e}"

        finally:
            try:
                if self.cap:
                    self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            except Exception:
                pass
            if self.cap:
                self.cap.release()
                self.cap = None

            if error_msg:
                self.finished.emit(False, error_msg)
                return

            if final_embedding is not None and final_embedding.size > 0:
                emb = final_embedding / (np.linalg.norm(final_embedding) + 1e-9)
                ok, message = persist_enrollment_embedding(self.student_no, emb.astype(np.float32))
                self.finished.emit(ok, message)
            elif self._running:
                self.finished.emit(False, "Enrollment Cancelled")

    def stop(self):
        self._running = False
        if self.cap:
            self.cap.release()
            self.cap = None
