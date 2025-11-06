import cv2, numpy as np
from PyQt6.QtCore import QThread, pyqtSignal


# Camera Thread
class CameraThread(QThread):
    frameCaptured = pyqtSignal(np.ndarray)

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._stop_thread = False

    def run(self):
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        while not self._stop_thread:
            ret, frame = cap.read()
            if ret:
                self.frameCaptured.emit(frame)
            self.msleep(10)

        cap.release()

    def stop(self):
        self._stop_thread = True
        self.wait()
