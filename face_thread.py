from PyQt6.QtCore import QThread, pyqtSignal
from face_recognition import verify_face


class FaceThread(QThread):
    result_ready = pyqtSignal(bool, str, tuple)
    def __init__(self, school_id, frame, gallery, parent=None):
        super().__init__(parent)
        self.school_id = school_id
        self.frame = frame.copy()
        self.gallery = gallery


    def run(self):
        ok, msg, box = verify_face(self.school_id, self.frame, self.gallery, return_box=True)
        if box is None:
            box = (0, 0, 0, 0)
        self.result_ready.emit(ok, msg, box)
