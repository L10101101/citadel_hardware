from PyQt6.QtCore import QTimer
from qr_verification import verify_qr_in_db
from utils import lookup_student, log_to_entry_logs
from async_email_notifier import notify_parent_task


class VerificationHandler:
    def __init__(self, main_window):
        self.main = main_window


    def fingerprint_verified(self, student_no):
        if self.main.verification_active:
            return
        self.main.verification_active = True

        if not student_no:
            self.main.set_status("Not Registered", "#FF6666")
            self.main.camera_handler.clear_camera_feed()
            QTimer.singleShot(2000, self.main.reset_verification_state)
            return

        success = log_to_entry_logs(student_no, self.main.last_logged, self.main.set_status, method_id=2)

        if success:
            student = lookup_student(student_no)
            if student:
                name, program, year, section = student
                self.main.update_ui_verified(student_no, name, program, year, section, "Access Granted")
                notify_parent_task(student_no)

        QTimer.singleShot(2000, self.main.reset_verification_state)


    def on_qr_input_received(self, qr_value):
        if self.main.verification_active:
            return
        self.main.fingerprint_thread.deactivate()

        qr_value = qr_value.strip()
        self.main.hiddenInput.clear()
        if not qr_value:
            return

        valid, _ = verify_qr_in_db(qr_value)
        if not valid:
            self.main.statusLabel.setText("Not Registered")
            self.main.set_status("Not Registered", "#FF6666")
            self.main.reset_info()
            return

        self.main.hiddenInput.setEnabled(False)
        self.main.verification_active = True
        self.main.current_qr = qr_value

        student = lookup_student(qr_value)
        if student:
            name, program, year, section = student
            self.main.update_ui_verified(qr_value, name, program, year, section, "QR Verified")
            self.main.set_status("QR Verified", "#FFA500")
            self.main.camera_handler.start_camera()
            self.main.face_timeout_timer.start(10000)
        else:
            self.main.set_status("Access Denied", "#FF6666")


    def on_face_timeout(self):
        if self.main.verification_active and self.main.current_qr:
            self.main.reset_verification_state()
            self.main.reset_info()
            self.main.set_status("Try Again", "#FFBF66")
            self.main.hiddenInput.setEnabled(True)
