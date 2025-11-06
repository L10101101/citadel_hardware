from PyQt6.QtCore import QThread, pyqtSignal

class FingerEnrollWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, student_no):
        super().__init__()
        self.student_no = student_no

    def run(self):
        try:
            from fingerprint_reader import FingerprintReader
            from fingerprint_enrollment import capture_fingerprint, save_to_db

            reader = FingerprintReader()
            template = capture_fingerprint(reader)
            save_to_db(self.student_no, template)
            reader.close()

            self.finished.emit(True, "Fingerprint enrollment successful.")
        except Exception as e:
            self.finished.emit(False, f"Error: {e}")
