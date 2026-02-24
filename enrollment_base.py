import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QImage
from face_enroll_worker import FaceEnrollWorker
from finger_enroll_thread import FingerEnrollWorker

from utils import resource_path
from db_utils import get_connection

logger = logging.getLogger(__name__)


class BaseEnrollmentHandler:    
    def __init__(self):
        self.selected_mode = None
        self.worker = None
    
    def setup_ui_common(self, btnFace, btnFinger, btnSubmit, txtStudentNo, lblStatus):
        self.btnFace = btnFace
        self.btnFinger = btnFinger
        self.btnSubmit = btnSubmit
        self.txtStudentNo = txtStudentNo
        self.lblStatus = lblStatus
        
        if self.btnFace:
            self.btnFace.setIcon(QIcon(resource_path("gui/assets/face-unselected.png")))
        if self.btnFinger:
            self.btnFinger.setIcon(QIcon(resource_path("gui/assets/fingerprint-unselected.png")))
        if self.btnSubmit:
            self.btnSubmit.setIcon(QIcon(resource_path("gui/assets/check.png")))
        
        if self.btnFace:
            self.btnFace.setChecked(False)
            self.btnFace.setCheckable(True)
        if self.btnFinger:
            self.btnFinger.setChecked(False)
            self.btnFinger.setCheckable(True)
        
        if self.txtStudentNo:
            self.txtStudentNo.setReadOnly(True)
        if self.btnSubmit:
            self.btnSubmit.setEnabled(False)
        
        if self.btnFace:
            self.btnFace.clicked.connect(lambda: self.select_mode("face"))
        if self.btnFinger:
            self.btnFinger.clicked.connect(lambda: self.select_mode("finger"))
        if self.btnSubmit:
            self.btnSubmit.clicked.connect(self.start_enrollment)
        
        self.set_status("Select Enrollment Type", "orange")
    
    def set_status(self, text: str, color: str):
        if self.lblStatus:
            self.lblStatus.setText(text)
            self.lblStatus.setStyleSheet(
                f"color: white; background-color: {color}; "
                "font-weight: bold; padding: 4px; border-radius: 4px;"
            )
    
    def select_mode(self, mode):
        self.selected_mode = mode
        
        if self.btnFace:
            self.btnFace.setChecked(mode == "face")
        if self.btnFinger:
            self.btnFinger.setChecked(mode == "finger")
        
        if self.txtStudentNo:
            self.txtStudentNo.setReadOnly(False)
            self.txtStudentNo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.txtStudentNo.setFocus(Qt.FocusReason.MouseFocusReason)
        
        if self.btnSubmit:
            self.btnSubmit.setEnabled(True)
        
        if mode == "face":
            self.set_status("Facial Enrollment Selected", "orange")
            if self.btnFace:
                self.btnFace.setIcon(QIcon("./gui/assets/face.png"))
            if self.btnFinger:
                self.btnFinger.setIcon(QIcon("./gui/assets/fingerprint-unselected.png"))
        else:
            self.set_status("Fingerprint Enrollment Selected", "orange")
            if self.btnFinger:
                self.btnFinger.setIcon(QIcon("./gui/assets/fingerprint.png"))
            if self.btnFace:
                self.btnFace.setIcon(QIcon("./gui/assets/face-unselected.png"))
    
    def update_camera_feed(self, frame, camera_label):
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimg = QImage(frame.tobytes(), w, h, bytes_per_line, QImage.Format.Format_BGR888)
        if camera_label:
            camera_label.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    camera_label.width(),
                    camera_label.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )
    
    def start_enrollment(self):
        student_no = self.txtStudentNo.text().strip() if self.txtStudentNo else ""
        
        if not student_no:
            self.set_status("Enter Student No.", "red")
            return
        
        if not self.student_exists(student_no):
            self.set_status(f"Student {student_no} Not Found", "red")
            return
        
        self.set_inputs_enabled(False)
        
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            self.worker = None
        
        camera_label = self.get_camera_label()
                
        if self.selected_mode == "face":
            self.set_status("Starting Facial Enrollment", "orange")
            self.worker = FaceEnrollWorker(student_no, label_widget=camera_label)
            self.worker.frameReady.connect(lambda frame: self.update_camera_feed(frame, camera_label))
            self.worker.finished.connect(self.on_enroll_done)
            self.worker.start()
        
        elif self.selected_mode == "finger":
            self.set_status("Starting Fingerprint Enrollment", "orange")
            self._handle_fingerprint_start()
            self.worker = FingerEnrollWorker(student_no)
            self.worker.finished.connect(self.on_enroll_done)
            self.worker.start()
        
        else:
            self.set_status("Select Enrollment", "red")
    
    def get_camera_label(self):
        return None
    
    def _handle_fingerprint_start(self):
        pass
    
    def set_inputs_enabled(self, enabled: bool):
        if self.btnFace:
            self.btnFace.setEnabled(enabled)
        if self.btnFinger:
            self.btnFinger.setEnabled(enabled)
        if self.txtStudentNo:
            self.txtStudentNo.setEnabled(enabled)
        if self.btnSubmit:
            self.btnSubmit.setEnabled(enabled)
        
        if enabled and not self.selected_mode:
            if self.txtStudentNo:
                self.txtStudentNo.setReadOnly(True)
    
    def student_exists(self, student_no):
        try:
            conn, source = get_connection("local")
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM students WHERE student_no = %s", (student_no,))
            found = cur.fetchone() is not None
            cur.close()
            conn.close()
            return found
        except Exception as e:
            logger.error("Database check failed for student %s: %s", student_no, e)
            return False
    
    def is_already_enrolled(self, student_no, mode):
        try:
            conn, source = get_connection("local")
            cur = conn.cursor()
            
            if mode == "face":
                cur.execute("SELECT has_facial_recognition FROM students WHERE student_no = %s", (student_no,))
                result = cur.fetchone()
                exists = bool(result and result[0])
            elif mode == "finger":
                cur.execute("SELECT 1 FROM fingerprints WHERE student_no = %s", (student_no,))
                exists = cur.fetchone() is not None
            else:
                exists = False
            
            cur.close()
            conn.close()
            return exists
        except Exception as e:
            logger.error("Enrollment check failed for student %s mode %s: %s", student_no, mode, e)
            return False
    
    def on_enroll_done(self, success, msg):
        color = "green" if success else "red"
        self.set_status(msg, color)
        
        self.selected_mode = None
        if self.txtStudentNo:
            self.txtStudentNo.clear()
            self.txtStudentNo.setReadOnly(True)
            self.txtStudentNo.setPlaceholderText("Select Enrollment Type")
        
        if self.btnFace:
            self.btnFace.setChecked(False)
            self.btnFace.setIcon(QIcon(resource_path("gui/assets/face-unselected.png")))
        if self.btnFinger:
            self.btnFinger.setChecked(False)
            self.btnFinger.setIcon(QIcon(resource_path("gui/assets/fingerprint-unselected.png")))
        
        self.set_inputs_enabled(True)
    
    def stop_enrollment(self):
        if self.worker and self.worker.isRunning():
            if hasattr(self.worker, "stop"):
                self.worker.stop()
            self.worker.wait(2000)
            self.worker = None
