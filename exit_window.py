import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QLineEdit, QGraphicsOpacityEffect, QLabel
from PyQt6.QtCore import QTimer, QDateTime, Qt
from PyQt6.QtGui import QPixmap

from main_ui import Ui_Citadel
from finger_thread import FingerprintThread
from camera_handler import CameraHandler
from exit_verification_handler import ExitVerificationHandler
from marquee_label import FooterMarquee

class ExitWindow(QMainWindow, Ui_Citadel):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Handlers
        self.camera_handler = CameraHandler(self)
        self.verification_handler = ExitVerificationHandler(self)

        # State
        self.reset_info()
        self.verification_active = False
        self.current_qr = None
        self.last_logged = {}
        self.footer_marquee = FooterMarquee(self.footerLabel, speed=35, padding=40, left_to_right=True)


        # Threads
        self.fingerprint_thread = FingerprintThread()
        self.fingerprint_thread.fingerprintDetected.connect(
            self.verification_handler.fingerprint_verified
        )
        self.fingerprint_thread.start()
        self.fingerprint_thread.activate()

        # QR input
        self.hiddenInput = QLineEdit(self)
        self.hiddenInput.setGeometry(-100, -100, 10, 10)
        self.hiddenInput.setFocus()
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

        # Overlay image
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

    # UI updates
    def update_ui_verified(self, student_no, name, program, year_section, status):
        self.nameLabel.setText(name)
        self.programLabel.setText(program)
        self.yearSecLabel.setText(year_section)
        self.idLabel.setText(student_no)
        self.entryLabel.setText(QDateTime.currentDateTime().toString("dddd | MMM d, yyyy | hh:mm AP"))
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


    def start_inactivity_timer(self):
        self.inactivity_timer.start()
        self.set_status("Ready", "#FFBF66")
        self.camera_handler.clear_camera_feed()

    def reset_info(self):
        self.camera_handler.clear_camera_feed()
        self.nameLabel.setText("-----")
        self.programLabel.setText("-----")
        self.yearSecLabel.setText("-----")
        self.idLabel.setText("-----")
        self.entryLabel.setText("-----")

    def reset_verification_state(self):
        self.verification_active = False
        self.current_qr = None
        self.set_status("Ready", "#FFBF66")
        self.hiddenInput.setEnabled(True)
        self.fingerprint_thread.activate()

    def update_datetime(self):
        self.dateTimeLabel.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))
        self.dateTimeLabel_2.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))

    def closeEvent(self, event):
        if getattr(self, 'fingerprint_thread', None):
            self.fingerprint_thread.stop()
            self.fingerprint_thread.wait(2000)
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ExitWindow()
    window.showFullScreen()
    sys.exit(app.exec())
