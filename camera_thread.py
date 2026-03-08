import cv2
import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal

CAPTURE_WIDTH = 3840
CAPTURE_HEIGHT = 2160
CAPTURE_FPS = 30


def _open_capture_with_fallback(index: int):
    previous_level = None
    try:
        if hasattr(cv2, "getLogLevel") and hasattr(cv2, "setLogLevel"):
            previous_level = cv2.getLogLevel()
            silent_level = getattr(cv2, "LOG_LEVEL_SILENT", 0)
            cv2.setLogLevel(silent_level)
    except Exception:
        previous_level = None

    backends = []
    if hasattr(cv2, "CAP_DSHOW"):
        backends.append(cv2.CAP_DSHOW)
    if hasattr(cv2, "CAP_MSMF"):
        backends.append(cv2.CAP_MSMF)
    if hasattr(cv2, "CAP_ANY"):
        backends.append(cv2.CAP_ANY)

    tried = set()
    try:
        for backend in backends:
            if backend in tried:
                continue
            tried.add(backend)
            cap = cv2.VideoCapture(index, backend)
            if cap.isOpened():
                return cap
            try:
                cap.release()
            except Exception:
                pass
        return cv2.VideoCapture(index)
    finally:
        try:
            if previous_level is not None and hasattr(cv2, "setLogLevel"):
                cv2.setLogLevel(previous_level)
        except Exception:
            pass


class CameraThread(QThread):
    frameCaptured = pyqtSignal(np.ndarray)
    deviceAvailabilityChanged = pyqtSignal(bool)

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._stop_thread = False
        self._last_device_available = None

    def _emit_device_availability(self, available: bool):
        if self._last_device_available is available:
            return
        self._last_device_available = available
        self.deviceAvailabilityChanged.emit(available)

    def run(self):
        cap = _open_capture_with_fallback(self.camera_index)
        self._emit_device_availability(cap.isOpened())
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAPTURE_FPS)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_AUTO_WB, 1)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
        except Exception:
            pass

        consecutive_failures = 0
        while not self._stop_thread:
            ret, frame = cap.read()
            if ret:
                consecutive_failures = 0
                self._emit_device_availability(True)
                self.frameCaptured.emit(frame)
            else:
                consecutive_failures += 1
                if consecutive_failures >= 8:
                    self._emit_device_availability(False)
            self.msleep(10)
        cap.release()

    def stop(self):
        self._stop_thread = True
        self.wait()
