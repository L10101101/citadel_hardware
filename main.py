import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QLineEdit, QLabel, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QPixmap

from main_ui import Ui_Citadel
from face_recognition import load_gallery
from utils import lookup_student, log_attendance
from async_email_notifier import notify_parent_task
from async_sms_notifier import notify_parent_sms_task
from sync_worker import start_sync_worker
from finger_thread import FingerprintThread
from camera_handler import CameraHandler
from verification_handler import VerificationHandler
from marquee_label import FooterMarquee
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
        self.verification_active = False
        self.current_qr = None
        self._suppress_feed = False
        self.last_logged = {}
        start_sync_worker(interval=10)
        self.footer_marquee = FooterMarquee(self.footerLabel, speed=35, padding=40, left_to_right=True)

        # Tabs
        self.actionMain = self.menuBar.addAction("Main")
        self.actionMain.triggered.connect(lambda: self.show_page("main"))
        self.enroll_logic = EnrollPage(self.page_enroll)
        self.actionEnroll = self.menuBar.addAction("Enroll")
        self.actionEnroll.triggered.connect(lambda: self.show_page("enroll"))
        self.actionSettings = self.menuBar.addAction("Settings")
        self.actionSettings.triggered.connect(lambda: self.stackedWidget.setCurrentWidget(self.page_settings))

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

        # Background Image
        self.overlay_image = QLabel(self)
        self.overlay_image.setPixmap(QPixmap("./gui/assets/building.png").scaled(
            400, 400, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))
        self.overlay_image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay_image.setStyleSheet("background: transparent; border: none;")
        self.overlay_image.resize(400, 400)
        self.overlay_image.move(self.width() - 200, self.height() - 200)
        opacity_effect = QGraphicsOpacityEffect()
        opacity_effect.setOpacity(0.75)
        self.overlay_image.setGraphicsEffect(opacity_effect)
        self.overlay_image.show()


    # Reset
    def show_page(self, page_name):
        if hasattr(self, "enroll_logic") and self.enroll_logic:
            self.enroll_logic.stop_enrollment()

        if page_name == "main":
            self.stackedWidget.setCurrentWidget(self.page_main)

            if hasattr(self, "fingerprint_thread"):
                self.fingerprint_thread.activate()

            try:
                from face_recognition import reset_models, load_gallery
                reset_models()
                self.gallery = load_gallery(force_reload=True)

                self.camera_handler.stop_camera()
                self.camera_handler._display_bgr = None
                self.camera_handler._display_info = None

                self.current_qr = None  

            except Exception as e:
                print(f"{e}")

        elif page_name == "enroll":
            self.stackedWidget.setCurrentWidget(self.page_enroll)

        else:
            self.stackedWidget.setCurrentWidget(self.pages.get(page_name, self.page_main))


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
        log_attendance(
            student_no,
            last_logged=self.last_logged,
            set_status=self.set_status,
            method_id=1
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
    

    def resizeEvent(self, event):
        self.overlay_image.move(self.width() - 180, self.height() - 250)
        super().resizeEvent(event)


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
        self.nameLabel.setText("-----")
        self.programLabel.setText("-----")
        self.yearSecLabel.setText("-----")
        self.idLabel.setText("-----")
        self.entryLabel.setText("-----")


    def eventFilter(self, obj, event):
        if self.stackedWidget.currentWidget() == self.page_main:
            self.hiddenInput.setFocus()
        return super().eventFilter(obj, event)


    def update_datetime(self):
        self.dateTimeLabel.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))
        self.dateTimeLabel_2.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))


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
