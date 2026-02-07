from PyQt6.QtCore import QThread, pyqtSignal

class FingerEnrollWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, student_no):
        super().__init__()
        self.student_no = student_no
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            from fingerprint_reader import FingerprintReader
            from fingerprint_enrollment import capture_fingerprint, save_to_cloud

            reader = FingerprintReader()
            template = capture_fingerprint(reader)
            save_to_cloud(self.student_no, template)
            reader.close()

            self.finished.emit(True, "Success")
        except Exception as e:
            msg = str(e)
            if "Device Missing" in msg:
                self.finished.emit(False, "Fingerprint device not detected")
            elif "Failed" in msg:
                self.finished.emit(False, "Fingerprint device not detected")
            else:
                self.finished.emit(False, f"{e}")
