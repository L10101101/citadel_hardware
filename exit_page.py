from PyQt6.QtWidgets import QWidget, QLineEdit, QGraphicsOpacityEffect, QLabel
from PyQt6.QtCore import QTimer, QDateTime, Qt
from PyQt6.QtGui import QPixmap

from finger_thread import FingerprintThread
from marquee_label import FooterMarquee
from exit_verification_handler import ExitVerificationHandler

class ExitPage:
    def __init__(self, page_exit: QWidget, main_window=None):
        self.page = page_exit
        self.main = main_window

        # Handler
        self.verification_handler = ExitVerificationHandler(self)

        # State
        self.verification_active = False
        self.current_qr = None
        self.last_logged = {}

        # Widgets
        self.statusLabelExit = self.page.findChild(QLabel, "statusLabelExit")
        self.entryLabelExit = self.page.findChild(QLabel, "entryLabelExit")
        self.nameLabelExit = self.page.findChild(QLabel, "nameLabelExit")
        self.programLabelExit = self.page.findChild(QLabel, "programLabelExit")
        self.idLabelExit = self.page.findChild(QLabel, "idLabelExit")
        self.yearSecLabelExit = self.page.findChild(QLabel, "yearSecLabelExit")

        # QR input
        self.hiddenInput = QLineEdit(self.page)
        self.hiddenInput.setGeometry(-100, -100, 10, 10)
        self.hiddenInput.returnPressed.connect(
            lambda: self.verification_handler.on_qr_input_received(self.hiddenInput.text())
        )

        # Fingerprint thread
        self.fingerprint_thread = FingerprintThread()
        self.fingerprint_thread.fingerprintDetected.connect(
            self.verification_handler.fingerprint_verified
        )
        self.fingerprint_thread.start()

        # Timers
        self.inactivity_timer = QTimer()
        self.inactivity_timer.setInterval(2000)
        QTimer.singleShot(500, self.start_inactivity_timer_exit)

        self.time_timer = QTimer()
        self.time_timer.start(1000)

        # Footer marquee
        self.footer_marquee = FooterMarquee(self.page.findChild(QLabel, "footerLabelExit"))

        # Initialize page info
        self.reset_info_exit()

    # -------------------
    # Page activation/deactivation
    # -------------------
    def activate(self):
        self.hiddenInput.setEnabled(True)
        self.hiddenInput.setFocus()
        self.fingerprint_thread.activate()

    def deactivate(self):
        self.hiddenInput.setEnabled(False)
        self.fingerprint_thread.deactivate()

    # -------------------
    # UI updates
    # -------------------
    def update_ui_verified(self, student_no, name, program, year_section, status):
        self.nameLabelExit.setText(name)
        self.programLabelExit.setText(program)
        self.yearSecLabelExit.setText(year_section)
        self.idLabelExit.setText(student_no)
        self.entryLabelExit.setText(QDateTime.currentDateTime().toString("dddd | MMM d, yyyy | hh:mm AP"))
        self.statusLabelExit.setText(status)

    def set_status_exit(self, text, color):
        self.statusLabelExit.setText(text)
        self.statusLabelExit.setStyleSheet(f"""
            background-color: {color};
            color: white;
            font-weight: bold;
            border-radius: 10px;
            padding: 5px;
        """)

    # -------------------
    # Timers / reset
    # -------------------
    def start_inactivity_timer_exit(self):
        self.inactivity_timer.start()
        self.set_status_exit("Ready", "#FFBF66")

    def reset_info_exit(self):
        self.nameLabelExit.setText("Name")
        self.programLabelExit.setText("Program")
        self.yearSecLabelExit.setText("Year and Section")
        self.idLabelExit.setText("Student No.")
        self.entryLabelExit.setText("Time")

    def reset_verification_state_exit(self):
        self.verification_active = False
        self.current_qr = None
        self.set_status_exit("Ready", "#FFBF66")
        self.hiddenInput.setEnabled(True)
        self.hiddenInput.setFocus()
        self.fingerprint_thread.activate()

    # -------------------
    # Overlay / resize
    # -------------------
    def resize(self):
        self.overlay_image.move(self.page.width() - 180, self.page.height() - 250)

    # -------------------
    # Shutdown
    # -------------------
    def shutdown(self):
        if getattr(self, 'fingerprint_thread', None):
            self.fingerprint_thread.stop()
            self.fingerprint_thread.wait(2000)
