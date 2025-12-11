import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QLineEdit, QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import QTimer, QDateTime
from PyQt6.QtGui import QAction

from main_ui import Ui_Citadel
from face_recognition import load_gallery
from utils import lookup_student, log_entry
from async_email_notifier import notify_parent_task
from async_sms_notifier import notify_parent_sms_task
from finger_thread import FingerprintThread
from camera_handler import CameraHandler
from verification_handler import VerificationHandler
from marquee_label import FooterMarquee
from exit_page import ExitPage
from enroll_page import EnrollPage

class MainWindow(QMainWindow, Ui_Citadel):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Handlers
        self.camera_handler = CameraHandler(self)
        self.verification_handler = VerificationHandler(self)

        # State
        self.reset_info()
        self.active_action = None
        self.verification_active = False
        self.current_qr = None
        self._suppress_feed = False
        self.last_logged = {}

        # Footer
        self.footer_marquee1 = FooterMarquee(self.footerLabel, speed=35, padding=40, left_to_right=True)
        self.footer_marquee2 = FooterMarquee(self.footerLabel_2, speed=35, padding=40, left_to_right=True)
        self.footer_marquee3 = FooterMarquee(self.footerLabelExit, speed=35, padding=40, left_to_right=True)

        # Main tab
        self.actionMain = self.menuBar.addAction("Main")
        self.actionMain.triggered.connect(lambda: self.show_page("main"))

        # Exit tab
        self.actionExit = self.menuBar.addAction("Exit")
        self.actionExit.triggered.connect(lambda: self.show_page("exit"))
        self.exit_page = ExitPage(self.page_exit, main_window=self)

        # Enroll tab
        self.actionEnroll = self.menuBar.addAction("Enroll")
        self.actionEnroll.triggered.connect(lambda: self.show_page("enroll"))
        self.enroll_page = EnrollPage(self.page_enroll, main_window=self)

        # Settings tab
        self.actionSettings = self.menuBar.addAction("Settings")
        self.actionSettings.triggered.connect(lambda: self.show_page("settings"))

        # Threads
        self.fingerprint_thread = FingerprintThread()
        self.fingerprint_thread.fingerprintDetected.connect(
            self.verification_handler.fingerprint_verified
        )
        self.fingerprint_thread.start()
        self.fingerprint_thread.activate()
        self.camera_thread = None

        # QR input
        self.hiddenInput = QLineEdit(self)
        self.hiddenInput.setGeometry(-100, -100, 10, 10)
        self.hiddenInput.setFocus()
        self.installEventFilter(self)
        self.hiddenInput.returnPressed.connect(
            lambda: self.verification_handler.on_qr_input_received(self.hiddenInput.text())
        )

        # Timers
        self.inactivity_timer = QTimer()
        self.inactivity_timer.setInterval(2000)
        QTimer.singleShot(500, self.start_inactivity_timer)

        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.update_datetime)
        self.time_timer.start(1000)

        self.face_timeout_timer = QTimer()
        self.face_timeout_timer.setSingleShot(True)
        self.face_timeout_timer.timeout.connect(
            self.verification_handler.on_face_timeout
        )

        # Load face gallery
        self.gallery = load_gallery()


    # Reset
    def show_page(self, page_name):
        # Stop enrollment if active
        if hasattr(self, "enroll_logic") and self.enroll_logic:
            self.enroll_logic.stop_enrollment()

        # Deactivate Main page
        self.hiddenInput.setEnabled(False)
        self.hiddenInput.clearFocus()
        self.fingerprint_thread.deactivate()

        # Main page
        if page_name == "main":
            self.stackedWidget.setCurrentWidget(self.page_main)
            self.set_active_tab(self.actionMain)
            self.fingerprint_thread.activate()
            self.hiddenInput.setEnabled(True)
            self.hiddenInput.setFocus()
            self.reset_verification_state()

        # Exit page
        elif page_name == "exit":
            self.stackedWidget.setCurrentWidget(self.page_exit)
            self.exit_page.activate()
            self.hiddenInput.setEnabled(False)
            self.exit_page.reset_verification_state_exit()

        # Enroll page
        elif page_name == "enroll":
            self.stackedWidget.setCurrentWidget(self.page_enroll)
            self.hiddenInput.setEnabled(False)
            self.reset_verification_state()

        # Settings page
        elif page_name == "settings":
            self.stackedWidget.setCurrentWidget(self.page_settings)

    def update_datetime(self):
        self.dateTimeLabel.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))
        self.dateTimeLabel_2.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))
        self.dateTimeLabelExit.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))


    def on_face_result(self, ok, info, box):
        if self._suppress_feed or not self.verification_active:
            return
        if ok:
            self.face_timeout_timer.stop()
            self.qr_verified_success(self.current_qr, info)
            self.current_qr = None
            QTimer.singleShot(2000, self.reset_verification_state)
        else:
            self.statusLabel.setText(info)
        if box:
            self.camera_handler.draw_face_box(box, ok)


    def qr_verified_success(self, student_no, name=None):
        student = lookup_student(student_no)
        if student:
            name, program, year_section = student
        else:
            name, program, year_section = "Unknown", "-", "-"

        self.update_ui_verified(student_no, name, program, year_section, "Access Granted")
        self.set_status("Access Granted", "#77EE77")
        log_entry(
            student_no,
            method_id=1,
            set_status=self.set_status,
        )

        notify_parent_task(student_no)
        notify_parent_sms_task(student_no)
        self.inactivity_timer.start()
        self.hiddenInput.setEnabled(True)
        self.fingerprint_thread.activate()


    # UI
    def update_ui_verified(self, student_no, name, program, year_section, status):
        self.nameLabel.setText(name)
        self.programLabel.setText(program)
        self.yearSecLabel.setText(year_section)
        self.idLabel.setText(student_no)
        self.entryLabel.setText(
            QDateTime.currentDateTime().toString("dddd | MMM d, yyyy | hh:mm AP")
        )
        self.statusLabel.setText(status)

    def set_status(self, text, color):
        self.statusLabel.setText(text)
        self.statusLabel.setStyleSheet(f"""
            background-color: {color};
            color: white;
            font-weight: bold;
            border-radius: 10px;
            padding: 5px;
        """)

    # Misc
    def start_inactivity_timer(self):
        self.inactivity_timer.start()
        self.set_status("Ready", "#FFBF66")
        self.camera_handler.clear_camera_feed()


    def reset_verification_state(self):
        self.verification_active = False
        self.current_qr = None
        self.set_status("Ready", "#FFBF66")
        self.hiddenInput.setEnabled(True)
        self.fingerprint_thread.activate()


    def reset_info(self):
        self.camera_handler.clear_camera_feed()
        self.nameLabel.setText("Name")
        self.idLabel.setText("Student No.")
        self.programLabel.setText("Program")
        self.yearSecLabel.setText("Year and Section")
        self.entryLabel.setText("Time")


    def eventFilter(self, obj, event):
        if self.stackedWidget.currentWidget() == self.page_main:
            self.hiddenInput.setFocus()
        return super().eventFilter(obj, event)


    def closeEvent(self, event):
        if getattr(self, 'face_thread', None) and self.face_thread.isRunning():
            self.face_thread.quit()
            self.face_thread.wait(2000)
        if getattr(self, 'camera_thread', None) and self.camera_thread.isRunning():
            self.camera_thread.stop()
            self.camera_thread.wait(2000)
        if getattr(self, 'fingerprint_thread', None):
            self.fingerprint_thread.stop()
            self.fingerprint_thread.wait(2000)
        super().closeEvent(event)


# Main
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showFullScreen()
    sys.exit(app.exec())
