from PyQt6.QtWidgets import QWidget, QPushButton, QLineEdit, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap

from enrollment_base import BaseEnrollmentHandler
from utils import resource_path


class EnrollPage(BaseEnrollmentHandler):
    def __init__(self, page_enroll: QWidget, main_window=None):
        super().__init__()
        self.page = page_enroll
        self.main = main_window
        self._hidden_input = None
        self._hidden_input_prev_policy = None

        btnFace = self.page.findChild(QPushButton, "btnFace")
        btnFinger = self.page.findChild(QPushButton, "btnFinger")
        btnSubmit = self.page.findChild(QPushButton, "btnSubmit")
        txtStudentNo = self.page.findChild(QLineEdit, "txtStudentNo")
        lblStatus = self.page.findChild(QLabel, "lblStatus")

        self.setup_ui_common(btnFace, btnFinger, btnSubmit, txtStudentNo, lblStatus)
        
        if self.txtStudentNo:
            self.txtStudentNo.setPlaceholderText("Student ID")

    def _locate_hidden_input(self):
        if self._hidden_input:
            return self._hidden_input
        wnd = self.page.window()
        hidden = getattr(wnd, "hiddenInput", None)
        if not hidden and wnd:
            hidden = wnd.findChild(QLineEdit, "hiddenInput")
        if hidden:
            self._hidden_input = hidden
        return hidden

    def _disable_hidden_input_focus(self):
        hidden = self._locate_hidden_input()
        if not hidden:
            return
        self._hidden_input_prev_policy = hidden.focusPolicy()
        hidden.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if hidden.hasFocus():
            hidden.clearFocus()

    def _restore_hidden_input_focus(self):
        hidden = self._locate_hidden_input()
        if not hidden or self._hidden_input_prev_policy is None:
            return
        hidden.setFocusPolicy(self._hidden_input_prev_policy)
        self._hidden_input_prev_policy = None

    def select_mode(self, mode):
        self._disable_hidden_input_focus()
        super().select_mode(mode)
        
        if mode == "face" and self.lblStatus:
            face_path = resource_path("gui/assets/face.png").replace("\\", "/")
            self.lblStatus.setText(
                f'<img src="file:///{face_path}" width="20" height="20"> Facial Enrollment Selected'
            )
        elif mode == "finger" and self.lblStatus:
            self.lblStatus.setPixmap(QPixmap(resource_path("gui/assets/fingerprint.png")))
            fp_path = resource_path("gui/assets/fingerprint.png").replace("\\", "/")
            self.lblStatus.setText(
                f'<img src="file:///{fp_path}" width="20" height="20"> Fingerprint Enrollment Selected'
            )

    def get_camera_label(self):
        return self.page.findChild(QLabel, "cameraFeed_2")

    def _handle_fingerprint_start(self):
        wnd = self.page.window()
        if hasattr(wnd, "fingerprint_thread"):
            wnd.fingerprint_thread.deactivate()

    def set_inputs_enabled(self, enabled: bool):
        super().set_inputs_enabled(enabled)
        if enabled:
            self._restore_hidden_input_focus()

    def on_enroll_done(self, success, msg):
        super().on_enroll_done(success, msg)
        
        if self.txtStudentNo:
            self.txtStudentNo.setPlaceholderText("Select Enrollment Type")
        
        wnd = self.page.window()
        
        if success and hasattr(wnd, "verification_handler"):
            try:
                from face_recognition import load_gallery, reset_models
                reset_models()
                new_gallery = load_gallery(force_reload=True)
                wnd.verification_handler.gallery = new_gallery
            except Exception as e:
                print(f"Failed to reload gallery: {e}")
        
        def reset_reader():
            if not hasattr(wnd, "fingerprint_thread"):
                return
            with wnd.fingerprint_thread._lock:
                if wnd.fingerprint_thread.reader:
                    try:
                        wnd.fingerprint_thread.reader.close()
                    except Exception:
                        pass
                wnd.fingerprint_thread.reader = None
            wnd.fingerprint_thread.activate()
        
        QTimer.singleShot(100, reset_reader)