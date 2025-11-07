from PyQt6.QtCore import QThread, pyqtSignal
from fingerprint_reader import FingerprintReader
from time import sleep
import threading


class FingerprintThread(QThread):
    fingerprintDetected = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader = None
        self._stop = False
        self._active = False
        self._lock = threading.Lock()


    def activate(self):
        with self._lock:
            if not self._active:
                self._active = True


    def deactivate(self):
        with self._lock:
            if self._active:
                self._active = False
                if self.reader:
                    try:
                        self.reader.close()
                    except Exception:
                        pass
                    self.reader = None


    def stop(self):
        self._stop = True
        self.deactivate()


    def run(self):
        while not self._stop:
            with self._lock:
                active = self._active

            if not active:
                sleep(0.5)
                continue

            if not self.reader:
                try:
                    self.reader = FingerprintReader()
                except Exception as e:
                    sleep(1)
                    continue

            try:
                template = self.reader.capture_template()
                if template:
                    result = self.reader.identify(template)
                    if result:
                        self.fingerprintDetected.emit(result)
                    else:
                        self.fingerprintDetected.emit("")
                else:
                    sleep(0.2)
            except Exception as e:
                if self.reader: 
                    try:
                        self.reader.close()
                    except Exception:
                        pass
                    self.reader = None
                sleep(1)

        self.deactivate()
