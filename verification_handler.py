from qr_verification import verify_qr_in_db
from utils import lookup_student, log_entry, log_exit, get_next_action, can_attempt_entry
from status_labels import (
    status_cloud_unavailable,
    status_entry_logged,
    status_exit_logged,
    status_no_fingerprint_data,
    status_not_enrolled,
    status_qr_verified,
    status_unrecognized,
)
from async_email_notifier import notify_parent_task, notify_exit
from async_sms_notifier import notify_parent_sms_task, notify_exit_sms

class VerificationHandler:
    def __init__(self, main_window):
        self.main = main_window

    def _schedule_reset_info(self):
        self.main.schedule_reset_info(7000)
    
    def _get_action(self, student_no: str):
        action, _ = get_next_action(student_no)
        return action

    def _update_ui(self, student_no: str, status_text: str, verification_mode: str | None = None):
        student = lookup_student(student_no)
        if student:
            name, program, year_section = student
        else:
            name, program, year_section = "Unknown", "-", "-"
        self.main.update_ui_verified(
            student_no,
            name,
            program,
            year_section,
            status_text,
            verification_mode=verification_mode,
        )

    def fingerprint_verified(self, student_no):
        if getattr(self.main, "emergency_mode", None) and self.main.emergency_mode.active:
            return
        if not self.main.ensure_fingerprint_ready(show_status=True):
            self.main.reset_verification_state()
            self._schedule_reset_info()
            return
        self.main.register_activity()
        if self.main.verification_active:
            return
        self.main.cancel_reset_info()
        self.main.reset_info()
        self.main.verification_active = True

        if not student_no:
            status_no_fingerprint_data(self.main.set_status)
            self.main.camera_handler.clear_camera_feed()
            self._schedule_reset_info()
            return

        action = self._get_action(student_no)
        if action == "error":
            status_cloud_unavailable(self.main.set_status)
            return

        if action == "exit":
            success = log_exit(
                student_no=student_no,
                method_id=2,
                set_status=self.main.set_status
            )
            if success:
                self._update_ui(student_no, "Exit Logged", verification_mode="qr_fingerprint")
                status_exit_logged(self.main.set_status)
                self.main.refresh_monitoring_summary()
                notify_exit(student_no)
                notify_exit_sms(student_no)
                self.main.schedule_reset_info(8000)
            else:
                self._schedule_reset_info()
        else:
            success = log_entry(
                student_no,
                method_id=2,
                set_status=self.main.set_status
            )
            if success:
                self._update_ui(student_no, "Entry Logged", verification_mode="qr_fingerprint")
                status_entry_logged(self.main.set_status)
                self.main.refresh_monitoring_summary()
                notify_parent_task(student_no)
                notify_parent_sms_task(student_no)
                self.main.schedule_reset_info(8000)
            else:
                self._schedule_reset_info()
    def on_qr_input_received(self, qr_value):
        if getattr(self.main, "emergency_mode", None) and self.main.emergency_mode.active:
            return
        if not self.main.ensure_qr_ready(show_status=True):
            self.main.hiddenInput.clear()
            self.main.reset_verification_state()
            self._schedule_reset_info()
            return
        self.main.register_activity()
        if self.main.verification_active:
            return
        self.main.cancel_reset_info()
        self.main.reset_info()
        self.main.fingerprint_thread.deactivate()
        # Restart idle slideshow countdown from the moment QR flow begins.
        self.main._reset_slideshow_timer()

        qr_value = qr_value.strip()
        self.main.hiddenInput.clear()
        if not qr_value:
            return

        valid, source = verify_qr_in_db(qr_value)
        if not valid:
            msg = "Cloud Unavailable" if source == "error" else "Not Enrolled"
            if source == "error":
                status_cloud_unavailable(self.main.set_status)
            else:
                status_not_enrolled(self.main.set_status)
            self._schedule_reset_info()
            return

        action = self._get_action(qr_value)
        if action == "error":
            status_cloud_unavailable(self.main.set_status)
            self._schedule_reset_info()
            return

        if action == "exit":
            student = lookup_student(qr_value)
            if not student:
                status_not_enrolled(self.main.set_status)
                self._schedule_reset_info()
                return
            self.main.hiddenInput.setEnabled(False)
            self.main.verification_active = True
            success = log_exit(
                student_no=qr_value,
                method_id=3,
                set_status=self.main.set_status
            )
            if success:
                self._update_ui(qr_value, "Exit Logged", verification_mode="qr_only")
                status_exit_logged(self.main.set_status)
                self.main.refresh_monitoring_summary()
                notify_exit(qr_value)
                notify_exit_sms(qr_value)
                self.main.schedule_reset_info(8000)
            else:
                self._schedule_reset_info()
            return

        if not can_attempt_entry(qr_value, set_status=self.main.set_status):
            self._schedule_reset_info()
            return

        self.main.hiddenInput.setEnabled(False)
        self.main.verification_active = True
        self.main.current_qr = qr_value
        self.main.start_face_verification_window()

        student = lookup_student(qr_value)
        if student:
            name, program, year_section = student
        else:
            name, program, year_section = "Unknown", "-", "-"

        self.main.update_ui_verified(
            qr_value,
            name,
            program,
            year_section,
            "QR Verified",
        )
        status_qr_verified(self.main.set_status)
        self.main.camera_handler.open_camera_window()
        self.main.camera_handler.start_camera()
        self.main.face_timeout_timer.start(10000)

    def on_face_timeout(self):
        if getattr(self.main, "emergency_mode", None) and self.main.emergency_mode.active:
            return
        if self.main.verification_active and self.main.current_qr:
            self.main.reset_verification_state()
        status_unrecognized(self.main.set_status)
        # Ensure slideshow does not appear immediately after timeout/failure.
        self.main._reset_slideshow_timer()
        self._schedule_reset_info()
        self.main.hiddenInput.setEnabled(True)
