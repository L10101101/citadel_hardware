import threading

from PyQt6.QtCore import QThread, pyqtSignal
from fingerprint_reader import FingerprintReader
from time import sleep


class FingerprintThread(QThread):
    fingerprintDetected = pyqtSignal(str)
    deviceAvailabilityChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reader = None
        self._stop = False
        self._active = False
        self._lock = threading.Lock()
        self._last_device_available = None

    def _emit_device_availability(self, available: bool):
        if self._last_device_available is available:
            return
        self._last_device_available = available
        self.deviceAvailabilityChanged.emit(available)

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
        empty_reads = 0
        while not self._stop:
            with self._lock:
                active = self._active

            if not active:
                sleep(0.5)
                continue

            if not self.reader:
                try:
                    self.reader = FingerprintReader()
                    self._emit_device_availability(True)
                    empty_reads = 0
                    sleep(0.5)
                except Exception as e:
                    self._emit_device_availability(False)
                    sleep(1)
                    continue

            try:
                template = self.reader.capture_template()
            except Exception:
                self._emit_device_availability(False)
                if self.reader:
                    try:
                        self.reader.close()
                    except Exception:
                        pass
                self.reader = None
                empty_reads = 0
                sleep(1)
                continue

            if template:
                empty_reads = 0
                try:
                    result = self.reader.identify(template)
                except Exception:
                    sleep(0.2)
                    continue
                if result:
                    self.fingerprintDetected.emit(result)
                else:
                    self.fingerprintDetected.emit("")
            else:
                empty_reads += 1
                if empty_reads >= 3:
                    try:
                        if not self.reader.is_connected():
                            self._emit_device_availability(False)
                            try:
                                self.reader.close()
                            except Exception:
                                pass
                            self.reader = None
                            empty_reads = 0
                            sleep(0.8)
                            continue
                        self._emit_device_availability(True)
                    except Exception:
                        self._emit_device_availability(False)
                        try:
                            self.reader.close()
                        except Exception:
                            pass
                        self.reader = None
                        empty_reads = 0
                        sleep(0.8)
                        continue
                sleep(0.2)

        self.deactivate()
