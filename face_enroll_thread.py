from PyQt6.QtCore import QThread, pyqtSignal

class FaceEnrollWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, student_no):
        super().__init__()
        self.student_no = student_no

    def run(self):
        try:
            from face_enrollment import capture_face_auto, extract_embedding, save_to_db
            face_crop = capture_face_auto()
            emb = extract_embedding(face_crop)
            save_to_db(self.student_no, emb)
            self.finished.emit(True, "Facial enrollment successful.")
        except Exception as e:
            self.finished.emit(False, f"Error: {e}")
