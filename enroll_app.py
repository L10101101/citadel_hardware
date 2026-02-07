import os
import sys

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QMessageBox,
    QCheckBox,
    QStyle,
)
from PyQt6.QtCore import QTimer, QDateTime, Qt, QSettings, QEventLoop, QEvent
from PyQt6.QtGui import QAction, QIcon, QPixmap, QTransform, QPainter, QColor
from enroll_ui import Ui_EnrollWindow
from login_ui import Ui_LoginDialog
from enrollment_base import BaseEnrollmentHandler
from marquee_label import FooterMarquee
from db_utils import get_connection, has_internet
from config_store import is_configured
from setup_wizard import run_setup_wizard
from utils import resource_path, set_sync_manager
from sync_dialog import SyncDialog

try:
    import bcrypt
except ImportError:
    bcrypt = None

class TermsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Terms and Conditions")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setObjectName("termsDialog")
        self.setStyleSheet(
            """
            #termsDialog {
                background-color: #f7f9fb;
                border-radius: 14px;
            }
            QTextEdit {
                border: none;
                background-color: transparent;
                font-size: 11px;
            }
            QPushButton {
                border-radius: 6px;
                padding: 6px 12px;
            }
            QCheckBox {
                font-size: 11px;
                color: #555;
            }
            #agreeBtn {
                background-color: #4CAF50;
                color: #ffffff;
            }
            #agreeBtn:disabled {
                background-color: #c8e6c9;
                color: #ffffff;
            }
            #exitBtn {
                background-color: #e0e0e0;
                color: #333333;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Terms and Conditions / Privacy Notice", self)
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #064F32;")
        layout.addWidget(title)

        from PyQt6.QtWidgets import QTextEdit
        text = QTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(
            "Citadel Enrollment - Terms and Conditions / Privacy Notice\n"
            "---------------------------------------------------------\n\n"
            "1. Purpose of Data Collection\n"
            "All personal and biometric information collected and processed through "
            "the Citadel Enrollment system is used solely for legitimate educational "
            "and institutional purposes, including but not limited to:\n"
            "  - Identity verification at campus entry and exit\n"
            "  - Attendance, monitoring, and security reporting\n"
            "  - Compliance with institutional policies and regulatory requirements\n\n"
            "2. Types of Data Collected\n"
            "The system may collect and store the following categories of data:\n"
            "  - Basic student and guardian details (e.g., name, ID number, contact information, program)\n"
            "  - Enrollment and verification data (e.g., QR codes, fingerprint templates, facial recognition data)\n"
            "  - System and usage logs (e.g., entry/exit timestamps, device and system events)\n\n"
            "3. Legal Basis and Data Privacy\n"
            "The collection and processing of data are carried out in accordance with "
            "the Data Privacy Act of 2012 (Republic Act No. 10173) and its Implementing "
            "Rules and Regulations, as well as other applicable data protection and "
            "digital information laws and guidelines. Data subjects have the right to "
            "be informed, to access, to object, to request correction, and to request "
            "erasure or blocking of personal data, subject to lawful limitations.\n\n"
            "4. Security and Encryption\n"
            "Appropriate technical and organizational measures are implemented to protect "
            "personal and biometric data against unauthorized access, alteration, disclosure, "
            "or destruction. These measures include, where applicable:\n"
            "  - Encryption of data in transit and at rest\n"
            "  - Secure authentication and access controls\n"
            "  - Segregation of duties and least-privilege access\n"
            "  - Regular backups and system monitoring\n\n"
            "5. Data Sharing and Retention\n"
            "Data collected by Citadel is used only within the University and its authorized "
            "service providers for the purposes stated above. Data will be retained only for "
            "as long as necessary to fulfill those purposes, comply with legal obligations, "
            "or protect the rights and interests of the University and its stakeholders.\n\n"
            "6. User Responsibilities\n"
            "By signing in and using this system, you agree to:\n"
            "  - Use your credentials responsibly and keep your password confidential\n"
            "  - Access only information and functions that you are authorized to use\n"
            "  - Immediately report any suspected unauthorized access, data breach, or misuse\n\n"
            "7. Contact and Inquiries\n"
            "For concerns or inquiries regarding your personal data, you may contact the "
            "University's Data Protection Officer or the Registrar's Office through the official channels.\n\n"
            "By proceeding, you acknowledge that you have read, understood, and agree to these terms."
        )
        text.verticalScrollBar().valueChanged.connect(self._on_terms_scrolled)
        self._terms_text = text
        layout.addWidget(text)

        self.agree_cb = QCheckBox("I have read and agree to the Terms and Conditions.", self)
        self.agree_cb.setEnabled(False)
        self.agree_cb.stateChanged.connect(self._update_agree_state)
        layout.addWidget(self.agree_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.exit_btn = QPushButton("Exit", self)
        self.exit_btn.setObjectName("exitBtn")
        self.agree_btn = QPushButton("Agree", self)
        self.agree_btn.setObjectName("agreeBtn")
        self.agree_btn.setEnabled(False)
        self.exit_btn.clicked.connect(self.reject)
        self.agree_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.exit_btn)
        btn_row.addWidget(self.agree_btn)
        layout.addLayout(btn_row)

        self.resize(720, 520)

    def _on_terms_scrolled(self):
        if not hasattr(self, '_terms_text'):
            return
        sb = self._terms_text.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum()
        self.agree_cb.setEnabled(at_bottom)
        if not at_bottom:
            self.agree_cb.setChecked(False)

    def _update_agree_state(self):
        self.agree_btn.setEnabled(self.agree_cb.isChecked())


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_LoginDialog()
        self.ui.setupUi(self)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setModal(True)
        self.setFixedSize(self.size())

        self.user_edit = self.ui.userEdit
        self.pass_edit = self.ui.passEdit
        self.remember_me_cb = self.ui.rememberMeCb
        self.status_label = self.ui.statusLabel
        self.terms_link = self.ui.termsLink
        self.login_btn = self.ui.loginBtn
        self.cancel_btn = self.ui.cancelBtn
        self.edit_conn_btn = self.ui.editConnBtn

        script_dir = os.path.dirname(os.path.abspath(__file__))
        ucc_paths = [
            os.path.join(script_dir, "gui", "assets", "ucc.png"),
            os.path.join(script_dir, "..", "gui", "assets", "ucc.png"),
            os.path.join(script_dir, "ucc.png"),
            "C:/Citadel/gui/assets/ucc.png",
        ]
        logo_paths = [
            os.path.join(script_dir, "gui", "assets", "logo.png"),
            os.path.join(script_dir, "..", "gui", "assets", "logo.png"),
            os.path.join(script_dir, "logo.png"),
            "C:/Citadel/gui/assets/logo.png",
        ]

        def _set_pixmap(label, paths, size):
            for path in paths:
                if os.path.exists(path):
                    pix = QPixmap(path)
                    if not pix.isNull():
                        pix = pix.scaled(
                            size,
                            size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        label.setPixmap(pix)
                        return

        _set_pixmap(self.ui.logoLabel, ucc_paths, 72)
        if hasattr(self.ui, "citadelLabel"):
            _set_pixmap(self.ui.citadelLabel, logo_paths, 80)

        self._password_visible = False
        eye_open_paths = [
            os.path.join(script_dir, "gui", "assets", "hide.png"),
            os.path.join(script_dir, "..", "gui", "assets", "hide.png"),
            os.path.join(script_dir, "eye-open.png"),
            "C:/Citadel/gui/assets/eye-open.png",
        ]
        eye_closed_paths = [
            os.path.join(script_dir, "gui", "assets", "view.png"),
            os.path.join(script_dir, "..", "gui", "assets", "view.png"),
            os.path.join(script_dir, "eye-closed.png"),
            "C:/Citadel/gui/assets/eye-closed.png",
        ]

        def _load_icon(paths):
            for p in paths:
                if os.path.exists(p):
                    icon = QIcon(p)
                    if not icon.isNull():
                        return icon
            return QIcon()

        self._eye_icon_hidden = _load_icon(eye_open_paths)
        self._eye_icon_visible = _load_icon(eye_closed_paths)

        if not self._eye_icon_hidden.isNull() and not self._eye_icon_visible.isNull():
            self._eye_action = QAction(self._eye_icon_hidden, "", self.pass_edit)
        else:
            self._eye_action = QAction("Show", self.pass_edit)

        self._eye_action.triggered.connect(self._toggle_password_visibility)
        self.pass_edit.addAction(self._eye_action, QLineEdit.ActionPosition.TrailingPosition)

        self.login_btn.clicked.connect(self._on_login_clicked)
        self.cancel_btn.clicked.connect(self.reject)
        self.pass_edit.returnPressed.connect(self._on_login_clicked)
        self.edit_conn_btn.clicked.connect(self._on_edit_connection)
        self.terms_link.linkActivated.connect(self._show_terms_and_conditions)

        self._load_remembered_login()

    def _on_login_clicked(self):
        username = self.user_edit.text().strip()
        password = self.pass_edit.text()

        if not username or not password:
            self.status_label.setText("Please enter both username and password.")
            return

        if not has_internet():
            QMessageBox.critical(
                self,
                "No Internet Connection",
                "Please check your network and try again.",
            )
            return

        if bcrypt is None:
            self.status_label.setText("Please install 'bcrypt'.")
            return

        self.login_btn.setEnabled(False)
        self.status_label.setText("Checking credentials...")
        QApplication.processEvents()

        try:
            conn, _ = get_connection("cloud")
            cur = conn.cursor()
            cur.execute(
                """
                SELECT password
                FROM accounts
                WHERE username = %s OR email = %s
                """,
                (username, username),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()

            if not row:
                self.status_label.setText("Invalid username or password.")
                self.login_btn.setEnabled(True)
                return

            stored_hash = row[0]
            if not stored_hash:
                self.status_label.setText("Account is missing a password hash.")
                self.login_btn.setEnabled(True)
                return

            h = stored_hash.encode("utf-8")
            if h.startswith(b"$2y$"):
                h = b"$2b$" + h[4:]

            if not bcrypt.checkpw(password.encode("utf-8"), h):
                self.status_label.setText("Invalid username or password.")
                self.login_btn.setEnabled(True)
                return

            self._save_remembered_login(username)
            self.accept()
        except Exception as e:
            self.status_label.setText(f"Login failed: {e}")
            self.login_btn.setEnabled(True)

    def _on_edit_connection(self):
        if run_setup_wizard(self):
            self.status_label.setText("")
            self.status_label.setToolTip("")

    def _settings(self):
        return QSettings("Citadel", "Enroll")

    def _load_remembered_login(self):
        s = self._settings()
        remember = s.value("remember_me", False, type=bool)
        username = s.value("username", "", type=str)
        self.remember_me_cb.setChecked(remember)
        if remember and username:
            self.user_edit.setText(username)

    def _save_remembered_login(self, username):
        s = self._settings()
        remember = self.remember_me_cb.isChecked()
        s.setValue("remember_me", remember)
        if remember and username:
            s.setValue("username", username)
        else:
            s.remove("username")

    def _toggle_password_visibility(self):
        self._password_visible = not self._password_visible
        mode = QLineEdit.EchoMode.Normal if self._password_visible else QLineEdit.EchoMode.Password
        self.pass_edit.setEchoMode(mode)
        if (
            hasattr(self, "_eye_icon_hidden")
            and hasattr(self, "_eye_icon_visible")
            and not self._eye_icon_hidden.isNull()
            and not self._eye_icon_visible.isNull()
        ):
            self._eye_action.setIcon(
                self._eye_icon_visible if self._password_visible else self._eye_icon_hidden
            )
        else:
            self._eye_action.setText("Hide" if self._password_visible else "Show")

    def _show_terms_and_conditions(self):
        from PyQt6.QtWidgets import QTextEdit

        dlg = QDialog(self)
        dlg.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        dlg.setModal(True)
        dlg.resize(640, 480)
        dlg.setObjectName("termsDialog")
        dlg.setStyleSheet(
            """
            #termsDialog {
                background-color: #f7f9fb;
                border-radius: 14px;
            }
            QTextEdit {
                border: none;
                background-color: transparent;
                font-size: 11px;
            }
            QPushButton {
                border-radius: 6px;
                padding: 6px 12px;
            }
            /* Thinner scrollbars inside the terms text */
            #termsDialog QScrollBar:vertical {
                width: 8px;
                background: transparent;
                margin: 0;
            }
            #termsDialog QScrollBar::handle:vertical {
                background: #c0c4cc;
                border-radius: 4px;
                min-height: 20px;
            }
            #termsDialog QScrollBar:horizontal {
                height: 8px;
                background: transparent;
                margin: 0;
            }
            #termsDialog QScrollBar::handle:horizontal {
                background: #c0c4cc;
                border-radius: 4px;
                min-width: 20px;
            }
            """
        )

        vbox = QVBoxLayout(dlg)

        text = QTextEdit(dlg)
        text.setReadOnly(True)
        text.setPlainText(
            "Citadel Enrollment - Terms and Conditions / Privacy Notice\n"
            "---------------------------------------------------------\n\n"
            "1. Purpose of Data Collection\n"
            "All personal and biometric information collected and processed through "
            "the Citadel Enrollment system is used solely for legitimate educational "
            "and institutional purposes, including but not limited to:\n"
            "  - Identity verification at campus entry and exit\n"
            "  - Attendance, monitoring, and security reporting\n"
            "  - Compliance with institutional policies and regulatory requirements\n\n"
            "2. Types of Data Collected\n"
            "The system may collect and store the following categories of data:\n"
            "  - Basic student and guardian details (e.g., name, ID number, contact information, program)\n"
            "  - Enrollment and verification data (e.g., QR codes, fingerprint templates, facial recognition data)\n"
            "  - System and usage logs (e.g., entry/exit timestamps, device and system events)\n\n"
            "3. Legal Basis and Data Privacy\n"
            "The collection and processing of data are carried out in accordance with "
            "the Data Privacy Act of 2012 (Republic Act No. 10173) and its Implementing "
            "Rules and Regulations, as well as other applicable data protection and "
            "digital information laws and guidelines. Data subjects have the right to "
            "be informed, to access, to object, to request correction, and to request "
            "erasure or blocking of personal data, subject to lawful limitations.\n\n"
            "4. Security and Encryption\n"
            "Appropriate technical and organizational measures are implemented to protect "
            "personal and biometric data against unauthorized access, alteration, disclosure, "
            "or destruction. These measures include, where applicable:\n"
            "  - Encryption of data in transit and at rest\n"
            "  - Secure authentication and access controls\n"
            "  - Segregation of duties and least-privilege access\n"
            "  - Regular backups and system monitoring\n\n"
            "5. Data Sharing and Retention\n"
            "Data collected by Citadel is used only within the University and its authorized "
            "service providers for the purposes stated above. Data will be retained only for "
            "as long as necessary to fulfill those purposes, comply with legal obligations, "
            "or protect the rights and interests of the University and its stakeholders.\n\n"
            "6. User Responsibilities\n"
            "By signing in and using this system, you agree to:\n"
            "  - Use your credentials responsibly and keep your password confidential\n"
            "  - Access only information and functions that you are authorized to use\n"
            "  - Immediately report any suspected unauthorized access, data breach, or misuse\n\n"
            "7. Contact and Inquiries\n"
            "For concerns or inquiries regarding your personal data, you may contact the "
            "University's Data Protection Officer or the Registrar's Office through the official channels.\n\n"
            "By proceeding to log in, you acknowledge that you have read, understood, and "
            "agree to these terms and conditions and the described data privacy practices."
        )

        vbox.addWidget(text)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close", dlg)
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        vbox.addLayout(btn_row)
        dlg.exec()


class EnrollWindow(QMainWindow, Ui_EnrollWindow, BaseEnrollmentHandler):
    def __init__(self, sync_manager=None):
        QMainWindow.__init__(self)
        self.sync_manager = sync_manager
        BaseEnrollmentHandler.__init__(self)
        self.setupUi(self)
        self._fix_resource_paths()

        self.setup_ui_common(
            self.btnFace,
            self.btnFinger,
            self.btnSubmit,
            self.txtStudentNo,
            self.lblStatus
        )
        
        if self.txtStudentNo:
            self.txtStudentNo.setPlaceholderText("Select Enrollment Type")
        
        self.footer_marquee2 = FooterMarquee(self.footerLabel, speed=35, padding=40, left_to_right=True)
        
        self.datetime_timer = QTimer()
        self.datetime_timer.timeout.connect(self.update_datetime)
        self.datetime_timer.start(1000)
        self.update_datetime()

        if hasattr(self, "syncLabel") and self.syncLabel:
            self.syncLabel.setCursor(Qt.CursorShape.PointingHandCursor)
            self.syncLabel.setToolTip("Click to sync from cloud (refresh student data)")
            self.syncLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.syncLabel.installEventFilter(self)
            self._sync_icon_base = self._get_sync_icon_pixmap()
            self._sync_rotation_angle = 0
            self._sync_spin_timer = QTimer(self)
            self._sync_spin_timer.timeout.connect(self._sync_spin_step)
            self._sync_watch_timer = QTimer(self)
            self._sync_watch_timer.timeout.connect(self._sync_watch_step)
            self._set_sync_icon(0)
        
        self._upload_dialog = QDialog(self)
        self._upload_dialog.setWindowTitle("Uploading biometric data")
        self._upload_dialog.setModal(True)
        self._upload_dialog.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self._upload_dialog)
        self._upload_label = QLabel("Uploading biometric data to cloud...\nPlease wait.")
        self._upload_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._upload_bar = QProgressBar()
        self._upload_bar.setRange(0, 0)
        layout.addWidget(self._upload_label)
        layout.addWidget(self._upload_bar)
        self._upload_dialog.setFixedSize(420, 150)
    
    def _get_sync_icon_pixmap(self):
        try:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
            pix = icon.pixmap(64, 64)
            if not pix.isNull():
                tinted = QPixmap(pix.size())
                tinted.fill(Qt.GlobalColor.transparent)
                painter = QPainter(tinted)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                painter.drawPixmap(0, 0, pix)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(tinted.rect(), QColor("#FB8C00"))
                painter.end()
                return tinted
        except Exception:
            pass
        return QPixmap(64, 64)

    def _set_sync_icon(self, rotation_degrees=0):
        if not hasattr(self, "syncLabel") or not self.syncLabel:
            return
        if not hasattr(self, "_sync_icon_base") or self._sync_icon_base.isNull():
            return
        target_size = self.syncLabel.size()
        size = max(1, min(target_size.width(), target_size.height()))
        padding = max(int(size * 0.15), 4)
        inner = max(1, size - (padding * 2))
        base = self._sync_icon_base.scaled(
            inner,
            inner,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if rotation_degrees != 0:
            t = QTransform()
            t.translate(base.width() / 2, base.height() / 2)
            t.rotate(rotation_degrees)
            t.translate(-base.width() / 2, -base.height() / 2)
            base = base.transformed(t, Qt.TransformationMode.SmoothTransformation)

        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        x = int((size - base.width()) / 2)
        y = int((size - base.height()) / 2)
        painter.drawPixmap(x, y, base)
        painter.end()
        self.syncLabel.setPixmap(canvas)

    def _sync_spin_step(self):
        self._sync_rotation_angle = (self._sync_rotation_angle + 30) % 360
        self._set_sync_icon(self._sync_rotation_angle)

    def _start_sync_animation(self):
        if hasattr(self, "_sync_spin_timer") and self._sync_spin_timer:
            self._sync_rotation_angle = 0
            self._sync_spin_timer.start(50)
        if hasattr(self, "_sync_watch_timer") and self._sync_watch_timer:
            self._sync_watch_timer.start(500)

    def _stop_sync_animation(self):
        if hasattr(self, "_sync_spin_timer") and self._sync_spin_timer:
            self._sync_spin_timer.stop()
        if hasattr(self, "_sync_watch_timer") and self._sync_watch_timer:
            self._sync_watch_timer.stop()
        self._set_sync_icon(0)

    def _sync_watch_step(self):
        if not hasattr(self, "sync_manager") or not self.sync_manager:
            return
        if self.sync_manager.is_syncing:
            return
        self._stop_sync_animation()
        msg = (getattr(self.sync_manager, "sync_progress", "") or "").lower()
        if self.lblStatus:
            if "no internet" in msg:
                self.lblStatus.setText("No Internet")
            elif "sync failed" in msg or "failed" in msg:
                self.lblStatus.setText("Sync failed")
            else:
                self.lblStatus.setText("Data refreshed")

    def _fix_resource_paths(self):
        for label, path in [
            (getattr(self, "logoLabel", None), "gui/assets/ucc.png"),
            (getattr(self, "engLogoLabel", None), "gui/assets/logo.png"),
        ]:
            if label is not None:
                p = resource_path(path)
                if os.path.exists(p):
                    label.setPixmap(QPixmap(p))

    def update_datetime(self):
        now = QDateTime.currentDateTime()
        date_str = now.toString("MMMM dd, yyyy | hh:mm AP")
        self.dateTimeLabel.setText(date_str)

    def eventFilter(self, obj, event):
        if obj == self.syncLabel and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._on_sync_clicked()
                return True
        return super().eventFilter(obj, event)

    def _on_sync_clicked(self):
        if not has_internet():
            QMessageBox.warning(
                self,
                "No Internet",
                "Please check your network connection and try again.",
            )
            return
        if not hasattr(self, "sync_manager") or not self.sync_manager:
            return
        if self.sync_manager.is_syncing:
            return
        prev_complete = getattr(self.sync_manager, "on_sync_complete", None)
        prev_error = getattr(self.sync_manager, "on_sync_error", None)

        def on_done():
            if callable(prev_complete):
                prev_complete()
            self.sync_manager.on_sync_complete = prev_complete
            self.sync_manager.on_sync_error = prev_error
            self._stop_sync_animation()
            if self.lblStatus:
                self.lblStatus.setText("Data refreshed")

        def on_err(err):
            if callable(prev_error):
                prev_error(err)
            self.sync_manager.on_sync_complete = prev_complete
            self.sync_manager.on_sync_error = prev_error
            self._stop_sync_animation()
            if self.lblStatus:
                self.lblStatus.setText("Sync failed" if "internet" not in (err or "").lower() else "No Internet")

        self.sync_manager.on_sync_complete = on_done
        self.sync_manager.on_sync_error = on_err
        self._start_sync_animation()
        if self.lblStatus:
            self.lblStatus.setText("Syncing...")
        started = self.sync_manager.sync_now(force_full=True, background=True)
        if not started:
            self._stop_sync_animation()
            if self.lblStatus:
                self.lblStatus.setText("Sync already running")
    
    def get_camera_label(self):
        return self.cameraFeed
    
    def on_enroll_done(self, success, msg):
        super().on_enroll_done(success, msg)
        
        if self.cameraFeed:
            self.cameraFeed.clear()
    """
    def on_upload_started(self):
        self._upload_label.setText("Uploading biometric data to cloud...\nPlease wait.")
        self._upload_bar.setRange(0, 0)
        self._upload_dialog.show()
    
    def on_upload_finished(self):
        self._upload_dialog.hide()
    """
    def closeEvent(self, event):
        reply = QMessageBox.question(
            self,
            "Exit Enrollment",
            "Exit Application?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.stop_enrollment()
            if hasattr(self, "sync_manager") and self.sync_manager:
                self.sync_manager.stop()
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    from system_checks import check_postgresql_installed
    ok, msg = check_postgresql_installed()
    if not ok:
        QMessageBox.critical(None, "PostgreSQL Required", msg)
        sys.exit(1)

    if not is_configured():
        if not run_setup_wizard():
            sys.exit(0)

    if not has_internet():
        QMessageBox.critical(
            None,
            "No Internet Connection",
            "Please check your network and try again.",
        )
        sys.exit(1)

    terms = TermsDialog()
    if terms.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    login = LoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    sync_dlg = SyncDialog(title="Citadel Enrollment")
    if sync_dlg.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    set_sync_manager(sync_dlg.sync_manager)
    sync_dlg.sync_manager.start()
    window = EnrollWindow(sync_manager=sync_dlg.sync_manager)
    window.showFullScreen()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
