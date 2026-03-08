import cv2
import time
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from camera_thread import CameraThread
from face_thread import FaceThread


class CameraPreviewWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("cameraPreviewWindow")
        self.setStyleSheet("background-color: #000;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.feed_label = QLabel(self)
        self.feed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed_label.setObjectName("cameraPreviewLabel")
        layout.addWidget(self.feed_label)

    def set_preview_size(self, size):
        self.setFixedSize(size, size)

class CameraHandler:
    def __init__(self, main_window):
        self.main = main_window
        self.camera_thread = None
        self._face_job_inflight = False
        self._last_face_job_started_at = 0.0
        self._face_job_interval_s = max(0.02, float(os.environ.get("FACE_JOB_INTERVAL_S", "0.05")))
        self._display_frame_interval_s = max(0.0, float(os.environ.get("CAMERA_DISPLAY_FRAME_INTERVAL_S", "0.04")))
        self._last_display_update_at = 0.0
        self._display_bgr = None
        self._display_info = None
        self._overlay_box = None
        self._overlay_ok = False
        self._overlay_message = None
        self._overlay_until = 0.0
        self._overlay_hold_s = max(0.1, float(os.environ.get("FACE_OVERLAY_HOLD_S", "0.35")))
        self.camera_window = None
        self.camera_overlay_label = None
        self._init_inline_preview()

    def _init_inline_preview(self):
        if self.camera_overlay_label is not None:
            return
        if not hasattr(self.main, "displayWidget"):
            return
        self.camera_overlay_label = QLabel(self.main.displayWidget)
        self.camera_overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_overlay_label.setObjectName("cameraInlinePreview")
        self.camera_overlay_label.setStyleSheet("background-color: #000; border-radius: 20px;")
        self.camera_overlay_label.setVisible(False)
        if hasattr(self.main, "displayLayout"):
            self.main.displayLayout.addWidget(self.camera_overlay_label, 0, 0, 1, 1)

    def open_camera_window(self):
        self._init_inline_preview()
        if self.camera_overlay_label is None:
            return
        self.camera_overlay_label.setVisible(True)
        self.camera_overlay_label.raise_()

    def close_camera_window(self):
        if self.camera_overlay_label is None:
            return
        self.camera_overlay_label.setVisible(False)

    def _suggested_window_size(self):
        screen = self.main.screen()
        if screen is None:
            return 640
        geom = screen.availableGeometry()
        return max(320, int(min(geom.width(), geom.height()) * 0.6))

    def _center_window(self, window):
        screen = self.main.screen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        x = geom.x() + (geom.width() - window.width()) // 2
        y = geom.y() + (geom.height() - window.height()) // 2
        window.move(x, y)

    def _target_label(self):
        if self.camera_overlay_label and self.camera_overlay_label.isVisible():
            return self.camera_overlay_label
        return getattr(self.main, "cameraFeed", None)

    def start_camera(self):
        if self.camera_thread and self.camera_thread.isRunning():
            return
        self.camera_thread = CameraThread(camera_index=0)
        self.camera_thread.frameCaptured.connect(self.update_camera_frame)
        if hasattr(self.main, "on_camera_device_availability_changed"):
            self.camera_thread.deviceAvailabilityChanged.connect(
                self.main.on_camera_device_availability_changed
            )
        self.camera_thread.start()

    def stop_camera(self):
        if self.camera_thread and self.camera_thread.isRunning():
            self.camera_thread.stop()
            self.camera_thread.wait()
        self.camera_thread = None
        self._face_job_inflight = False
        self.clear_camera_feed()

    def _can_launch_face_job(self):
        if not getattr(self.main, "verification_active", False):
            return False
        if not self.main.current_qr:
            return False
        existing = getattr(self.main, "face_thread", None)
        if self._face_job_inflight:
            return False
        if existing and existing.isRunning():
            self._face_job_inflight = True
            return False
        now = time.monotonic()
        if (now - self._last_face_job_started_at) < self._face_job_interval_s:
            return False
        return True

    def _on_face_thread_finished(self, thread_obj):
        self._face_job_inflight = False
        if getattr(self.main, "face_thread", None) is thread_obj:
            self.main.face_thread = None
        thread_obj.deleteLater()

    def update_camera_frame(self, frame):
        if self.main._suppress_feed:
            return
        label = self._target_label()
        if label is None:
            return
        now = time.monotonic()
        self.main.original_frame = frame
        should_update_display = (
            self._display_info is None
            or (now - self._last_display_update_at) >= self._display_frame_interval_s
        )
        if should_update_display:
            h, w, _ = frame.shape
            crop_size = min(h, w)
            x_start = (w - crop_size) // 2
            y_start = (h - crop_size) // 2
            square_frame = frame[y_start:y_start + crop_size, x_start:x_start + crop_size]

            target_size = min(max(1, label.width()), max(1, label.height()))
            display_bgr = cv2.resize(square_frame, (target_size, target_size))
            display_bgr = cv2.flip(display_bgr, 1)

            self._display_bgr = display_bgr.copy()
            self._display_info = {
                "x_start": x_start,
                "y_start": y_start,
                "crop_size": crop_size,
                "display_w": target_size,
                "display_h": target_size,
                "mirrored": True
            }
            disp = self._display_bgr.copy()
            disp = self._apply_overlay(disp)
            self.update_pixmap(disp)
            self._last_display_update_at = now

        if self._can_launch_face_job():
            thread = FaceThread(self.main.current_qr, self.main.original_frame, self.main.gallery)
            self.main.face_thread = thread
            self._face_job_inflight = True
            self._last_face_job_started_at = time.monotonic()
            thread.result_ready.connect(self.main.on_face_result)
            thread.finished.connect(lambda thr=thread: self._on_face_thread_finished(thr))
            thread.start()

    def update_pixmap(self, bgr_frame):
        label = self._target_label()
        if label is None:
            return
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h_img, w_img = rgb_frame.shape[:2]
        qt_image = QImage(rgb_frame.data, w_img, h_img, 3 * w_img, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image).scaled(
            label.width(),
            label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        label.setPixmap(pixmap)

    def draw_face_box(self, box, ok, message=None):
        self._overlay_box = box
        self._overlay_ok = bool(ok)
        self._overlay_message = message
        self._overlay_until = time.monotonic() + self._overlay_hold_s
        if self._display_info is None or self._display_bgr is None:
            return
        disp = self._display_bgr.copy()
        disp = self._apply_overlay(disp)
        self.update_pixmap(disp)

    def _apply_overlay(self, disp):
        if self._display_info is None:
            return disp
        if self._overlay_box is None or time.monotonic() > self._overlay_until:
            return disp
        x1, y1, x2, y2 = self._overlay_box
        info = self._display_info
        dx1 = max(0, min(info["crop_size"], x1 - info["x_start"]))
        dx2 = max(0, min(info["crop_size"], x2 - info["x_start"]))
        dy1 = max(0, min(info["crop_size"], y1 - info["y_start"]))
        dy2 = max(0, min(info["crop_size"], y2 - info["y_start"]))
        sx = info["display_w"] / info["crop_size"]
        sy = info["display_h"] / info["crop_size"]
        dx1, dx2 = int(dx1 * sx), int(dx2 * sx)
        dy1, dy2 = int(dy1 * sy), int(dy2 * sy)
        if info["mirrored"]:
            dx1, dx2 = info["display_w"] - dx2, info["display_w"] - dx1
        color = (0, 255, 0) if self._overlay_ok else (0, 0, 255)
        thickness = max(2, int(round(info["display_w"] / 300)))
        if x2 > x1 and y2 > y1:
            cv2.rectangle(disp, (dx1, dy1), (dx2, dy2), color, thickness)
        if self._overlay_message:
            font_scale = max(0.55, info["display_w"] / 1100.0)
            text_thickness = max(2, int(round(info["display_w"] / 360)))
            (text_w, text_h), baseline = cv2.getTextSize(
                self._overlay_message, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness
            )
            pad = max(8, int(round(info["display_w"] / 100)))
            tx = max(pad, info["display_w"] - text_w - pad)
            ty = max(text_h + pad, text_h + pad)
            bg_x1 = max(0, tx - pad // 2)
            bg_y1 = max(0, ty - text_h - pad // 2)
            bg_x2 = min(info["display_w"], tx + text_w + pad // 2)
            bg_y2 = min(info["display_h"], ty + baseline + pad // 2)
            cv2.rectangle(disp, (bg_x1, bg_y1), (bg_x2, bg_y2), (0, 0, 0), -1)
            cv2.putText(
                disp,
                self._overlay_message,
                (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (255, 255, 255),
                text_thickness,
                cv2.LINE_AA,
            )
        return disp

    def clear_camera_feed(self):
        self._overlay_box = None
        self._overlay_message = None
        self._overlay_until = 0.0
        from utils import resource_path
        pixmap = QPixmap(resource_path("gui/assets/user.png"))
        label = self._target_label()
        if label is not None:
            label.setPixmap(pixmap)
        if hasattr(self.main, "status_labels"):
            self.main.status_labels.set_camera_background("#FFBF66")  # Ready color
