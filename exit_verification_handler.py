from PyQt6.QtCore import QTimer
from utils import lookup_student, log_to_exit_logs

class ExitVerificationHandler:
    def __init__(self, main_window):
        self.main = main_window

    def fingerprint_verified(self, student_no):
        if self.main.verification_active:
            return
        self.main.verification_active = True

        if not student_no:
            self.main.set_status("Not Registered", "#FF6666")
            QTimer.singleShot(2000, self.main.reset_verification_state)
            return

        success = log_to_exit_logs(
            student_no,
            self.main.last_logged,
            set_status=self.main.set_status,
            method_id=2
        )

        if success:
            student = lookup_student(student_no)
            if student:
                name, program, year_section = student
                self.main.update_ui_verified(student_no, name, program, year_section, "Exit Logged")
            self.main.set_status("Exit Logged", "#77EE77")

        QTimer.singleShot(2000, self.main.reset_verification_state)

    def on_qr_input_received(self, qr_value):
        if self.main.verification_active:
            return
        self.main.fingerprint_thread.deactivate()

        qr_value = qr_value.strip()
        self.main.hiddenInput.clear()
        if not qr_value:
            return

        student = lookup_student(qr_value)
        if student:
            name, program, year_section = student
            self.main.update_ui_verified(qr_value, name, program, year_section, "Exit QR Logged")
            self.main.set_status("Exit QR Logged", "#77EE77")
            log_to_exit_logs(
                qr_value,
                self.main.last_logged,
                set_status=self.main.set_status,
                method_id=3
            )
        else:
            self.main.set_status("Access Denied", "#FF6666")

        QTimer.singleShot(2000, self.main.reset_verification_state)
