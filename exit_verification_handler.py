from PyQt6.QtCore import QTimer
from utils import lookup_student, log_exit

class ExitVerificationHandler:
    def __init__(self, exit_page):
        self.exit_page = exit_page

    def fingerprint_verified(self, student_no):
        if self.exit_page.verification_active:
            return
        self.exit_page.verification_active = True

        if not student_no:
            self.exit_page.set_status_exit("Not Registered", "#FF6666")
            QTimer.singleShot(2000, self.exit_page.reset_verification_state_exit)
            return

        success = log_exit(
            student_no=student_no,
            method_id=2,
            set_status=self.exit_page.set_status_exit
        )

        if success:
            student = lookup_student(student_no)
            if student:
                name, program, year_section = student
                self.exit_page.update_ui_verified(student_no, name, program, year_section, "Exit Logged")
            self.exit_page.set_status_exit("Exit Logged", "#77EE77")

        QTimer.singleShot(2000, self.exit_page.reset_verification_state_exit)

    def on_qr_input_received(self, qr_value):
        if self.exit_page.verification_active:
            return
        self.exit_page.fingerprint_thread.deactivate()

        qr_value = qr_value.strip()
        self.exit_page.hiddenInput.clear()
        if not qr_value:
            return

        student = lookup_student(qr_value)
        if student:
            name, program, year_section = student
            self.exit_page.update_ui_verified(qr_value, name, program, year_section, "Exit QR Logged")
            self.exit_page.set_status_exit("Exit QR Logged", "#77EE77")
            log_exit(
                student_no=qr_value,
                method_id=3,
                set_status=self.exit_page.set_status_exit
            )
        else:
            self.exit_page.set_status_exit("Access Denied", "#FF6666")

        QTimer.singleShot(2000, self.exit_page.reset_verification_state_exit)
