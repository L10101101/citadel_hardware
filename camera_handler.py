import cv2
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from camera_thread import CameraThread
from face_thread import FaceThread

class CameraHandler:
    def __init__(self, main_window):
        self.main = main_window
        self.camera_thread = None
        self._display_bgr = None
        self._display_info = None

    # -------------------- Camera Control --------------------
    def start_camera(self):
        if self.camera_thread and self.camera_thread.isRunning():
            return
        self.camera_thread = CameraThread(camera_index=0)
        self.camera_thread.frameCaptured.connect(self.update_camera_frame)
        self.camera_thread.start()

    def stop_camera(self):
        if self.camera_thread and self.camera_thread.isRunning():
            self.camera_thread.stop()
            self.camera_thread.wait()
            self.camera_thread = None
        self.clear_camera_feed()

    # -------------------- Frame Update --------------------
    def update_camera_frame(self, frame):
        if self.main._suppress_feed:
            return

        self.main.original_frame = frame
        h, w, _ = frame.shape
        crop_size = min(h, w)
        x_start = (w - crop_size) // 2
        y_start = (h - crop_size) // 2
        square_frame = frame[y_start:y_start + crop_size, x_start:x_start + crop_size]

        target_size = min(max(1, self.main.cameraFeed.width()), max(1, self.main.cameraFeed.height()))
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

        self.update_pixmap(display_bgr)

        if self.main.current_qr and self.main.gallery and (not hasattr(self.main, 'face_thread') or not self.main.face_thread.isRunning()):
            self.main.face_thread = FaceThread(self.main.current_qr, self.main.original_frame, self.main.gallery)
            self.main.face_thread.result_ready.connect(self.main.on_face_result)
            self.main.face_thread.start()

    def update_pixmap(self, bgr_frame):
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h_img, w_img = rgb_frame.shape[:2]
        qt_image = QImage(rgb_frame.data, w_img, h_img, 3*w_img, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image).scaled(
            self.main.cameraFeed.width(),
            self.main.cameraFeed.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.main.cameraFeed.setPixmap(pixmap)

    def draw_face_box(self, box, ok):
        x1, y1, x2, y2 = box
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
        disp = self._display_bgr.copy()
        color = (0, 255, 0) if ok else (0, 0, 255)
        thickness = max(2, int(round(info["display_w"] / 300)))
        cv2.rectangle(disp, (dx1, dy1), (dx2, dy2), color, thickness)
        self.update_pixmap(disp)

    def clear_camera_feed(self):
        pixmap = QPixmap("./gui/assets/user.png")
        self.main.cameraFeed.setPixmap(pixmap)
        self.main.cameraFeed.setStyleSheet("background-color: white;")
