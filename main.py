import sys

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QMessageBox,
    QDialog,
)
from PyQt6.QtCore import QTimer, QDateTime
from PyQt6.QtGui import QAction, QPixmap

from main_ui import Ui_Citadel
from utils import lookup_student, log_entry, resource_path
from async_email_notifier import notify_parent_task
from async_sms_notifier import notify_parent_sms_task
from finger_thread import FingerprintThread
from camera_handler import CameraHandler
from verification_handler import VerificationHandler
from marquee_label import FooterMarquee
from exit_page import ExitPage
from connection_monitor import ConnectionMonitor
from data_sync import DataSyncManager
from sync_dialog import SyncDialog
from utils import set_sync_manager

class MainWindow(QMainWindow, Ui_Citadel):
    def __init__(self, sync_manager: DataSyncManager):
        super().__init__()
        self.setupUi(self)
        self._fix_resource_paths()
        self.camera_handler = CameraHandler(self)
        self.verification_handler = VerificationHandler(self)
        self.reset_info()
        self.active_action = None
        self.verification_active = False
        self.current_qr = None
        self._suppress_feed = False
        self.last_logged = {}

        self.footer_marquee1 = FooterMarquee(self.footerLabel, speed=35, padding=40, left_to_right=True)
        self.footer_marquee3 = FooterMarquee(self.footerLabelExit, speed=35, padding=40, left_to_right=True)

        self.actionMain = QAction("Entrance", self)
        self.actionMain.setCheckable(True)
        self.toolBar.addAction(self.actionMain)
        self.actionMain.triggered.connect(lambda: self.show_page("main"))
        self.actionExit = QAction("Exit", self)
        self.actionExit.setCheckable(True)
        self.toolBar.addAction(self.actionExit)
        self.actionExit.triggered.connect(lambda: self.show_page("exit"))
        self.exit_page = ExitPage(self.page_exit, main_window=self)

        self.fingerprint_thread = FingerprintThread()
        self.fingerprint_thread.fingerprintDetected.connect(
            self.verification_handler.fingerprint_verified
        )
        self.fingerprint_thread.start()
        self.fingerprint_thread.activate()
        self.camera_thread = None

        self.hiddenInput = QLineEdit(self)
        self.hiddenInput.setGeometry(-100, -100, 10, 10)
        self.hiddenInput.setFocus()
        self.installEventFilter(self)
        self.hiddenInput.returnPressed.connect(
            lambda: self.verification_handler.on_qr_input_received(self.hiddenInput.text())
        )

        self.toolBar.show()
        self.show_page("main")

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

        self.connection_monitor = ConnectionMonitor(self)
        self.sync_manager = sync_manager
        set_sync_manager(self.sync_manager)
        self.sync_manager.start()

        try:
            from face_recognition import load_gallery
            self.gallery = load_gallery()
        except Exception:
            self.gallery = []

    def _fix_resource_paths(self):
        import os
        for label, path in [
            (getattr(self, "syncUccLogo", None), "gui/assets/ucc.png"),
            (getattr(self, "syncCitadelLogo", None), "gui/assets/logo.png"),
            (getattr(self, "logoLabel", None), "gui/assets/UCC_Logo.ico"),
            (getattr(self, "engLogoLabel", None), "gui/assets/logo.png"),
            (getattr(self, "logoLabelExit", None), "gui/assets/UCC_Logo.ico"),
            (getattr(self, "engLogoLabelExit", None), "gui/assets/logo.png"),
        ]:
            if label is not None:
                p = resource_path(path)
                if os.path.exists(p):
                    label.setPixmap(QPixmap(p))

    def show_page(self, page_name):
        self.hiddenInput.setEnabled(False)
        self.hiddenInput.clearFocus()
        self.fingerprint_thread.deactivate()

        if page_name == "main":
            self.stackedWidget.setCurrentWidget(self.page_main)
            self.set_active_tab(self.actionMain)
            self.fingerprint_thread.activate()
            self.hiddenInput.setEnabled(True)
            self.hiddenInput.setFocus()
            self.reset_verification_state()

        elif page_name == "exit":
            self.stackedWidget.setCurrentWidget(self.page_exit)
            self.set_active_tab(self.actionExit)
            self.exit_page.activate()
            self.exit_page.reset_verification_state_exit()

    def set_active_tab(self, action):
        for act in [self.actionMain, self.actionExit]:
            act.setChecked(False)
        action.setChecked(True)
     
    def update_datetime(self):
        self.dateTimeLabel.setText(QDateTime.currentDateTime().toString("MMMM dd, yyyy | hh:mm:ss AP"))
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

        self.update_ui_verified(student_no, name, program, year_section, "Student Enrolled")
        self.set_status("Student Enrolled", "#77EE77")
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
        self._set_camera_feed_background(color)

    def _set_camera_feed_background(self, color):
        """Update camera feed background color to match status (shows in letterboxing, does not cover video)."""
        if hasattr(self, "cameraFeed") and self.cameraFeed:
            self.cameraFeed.setStyleSheet(f"""
                background-color: {color};
                border-radius: 20px;
            """)

    def start_inactivity_timer(self):
        self.inactivity_timer.start()
        self.set_status("Ready", "#FFBF66")
        self.camera_handler.clear_camera_feed()

    def reset_info(self):
        self.camera_handler.clear_camera_feed()
        self.nameLabel.setText("Name")
        self.idLabel.setText("Student No.")
        self.programLabel.setText("Program")
        self.yearSecLabel.setText("Year and Section")
        self.entryLabel.setText("Time")

    def reset_verification_state(self):
        self.verification_active = False
        self.current_qr = None
        self.set_status("Ready", "#FFBF66")
        self.hiddenInput.setEnabled(True)
        self.fingerprint_thread.activate()

    def showEvent(self, event):
        super().showEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if self.stackedWidget.currentWidget() == self.page_main:
            self.hiddenInput.setFocus()
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self,
            "Exit Citadel",
            "Exit Application?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            event.ignore()
            return

        if hasattr(self, "connection_monitor"):
            self.connection_monitor.stop()
        if hasattr(self, "sync_manager"):
            self.sync_manager.stop()
        if getattr(self, "face_thread", None) and self.face_thread.isRunning():
            self.face_thread.quit()
            self.face_thread.wait(2000)
        if getattr(self, "camera_thread", None) and self.camera_thread.isRunning():
            self.camera_thread.stop()
            self.camera_thread.wait(2000)
        if getattr(self, "fingerprint_thread", None):
            self.fingerprint_thread.stop()
            self.fingerprint_thread.wait(2000)
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    from system_checks import check_postgresql_installed
    ok, msg = check_postgresql_installed()
    if not ok:
        QMessageBox.critical(None, "PostgreSQL Required", msg)
        sys.exit(1)
    from config_store import is_configured
    from setup_wizard import run_setup_wizard
    if not is_configured():
        if not run_setup_wizard():
            sys.exit(0)

    # On startup we attempt a cloud sync. If there's no internet,
    # SyncDialog (with allow_offline=True) will auto-continue and
    # Citadel main will run in offline mode using the local cache.
    sync_dlg = SyncDialog(title="Citadel", allow_offline=True)
    if sync_dlg.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)
    set_sync_manager(sync_dlg.sync_manager)
    window = MainWindow(sync_manager=sync_dlg.sync_manager)
    window.showFullScreen()
    sys.exit(app.exec())
