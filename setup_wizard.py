import sys
import os
try:
    import winreg
except ImportError:
    winreg = None


import psycopg2

from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWizard,
    QWizardPage,
    QFormLayout,
    QMessageBox,
    QCheckBox,
    QGroupBox,
    QFileDialog,
    QSpinBox,
    QRadioButton,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from psycopg2 import Binary

from config_store import (
    save_config,
    keyring_available,
    get_local_db,
    get_cloud_db,
    get_smtp_config,
    get_twilio_config,
    get_fernet_key,
    get_sync_config,
    get_slideshow_config,
    get_app_config,
    is_configured,
)
from app_logging import configure_logging

class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Citadel Setup")
        self.setSubTitle("Welcome to the Citadel configuration wizard.")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "This wizard will guide you through configuring Citadel for your environment.\n\n"
            "You will need to provide:\n"
            "• Local database connection (PostgreSQL)\n"
            "• Cloud database connection (PostgreSQL)\n"
            "• SMTP settings for email notifications\n"
            "• Twilio settings for SMS notifications\n"
            "• Fernet key for face/fingerprint encryption (or auto-generate)\n\n"
            "Sensitive values (passwords, tokens) are stored in your system's credential store.\n"
            "Other settings are stored in an encrypted configuration file."
        ))
        if not keyring_available():
            layout.addWidget(QLabel(
                "\n⚠ Warning: The 'keyring' package is not installed. "
                "Run: pip install keyring"
            ))

class LocalDbPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Local Database")
        self.setSubTitle("Configure the local PostgreSQL database (used for offline cache).")
        layout = QFormLayout(self)

        self.dbname = QLineEdit()
        self.dbname.setPlaceholderText("e.g. citadel_local")
        layout.addRow("Database name:", self.dbname)

        self.user = QLineEdit()
        self.user.setPlaceholderText("e.g. postgres")
        layout.addRow("User:", self.user)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Local DB password")
        layout.addRow("Password:", self.password)

        self.host = QLineEdit()
        self.host.setPlaceholderText("e.g. 127.0.0.1 or localhost")
        self.host.setText("127.0.0.1")
        layout.addRow("Host:", self.host)

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(5432)
        layout.addRow("Port:", self.port)

        self.registerField("local_dbname", self.dbname)
        self.registerField("local_user", self.user)
        self.registerField("local_password", self.password)
        self.registerField("local_host", self.host)
        self.registerField("local_port", self.port)

        for w in (self.dbname, self.user, self.password, self.host):
            w.textChanged.connect(self.completeChanged)

    def isComplete(self):
        return bool(
            self.dbname.text().strip()
            and self.user.text().strip()
            and self.password.text().strip()
            and self.host.text().strip()
        )

class CloudDbPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Cloud Database")
        self.setSubTitle("Configure the cloud PostgreSQL database (central server).")
        layout = QFormLayout(self)

        self.dbname = QLineEdit()
        self.dbname.setPlaceholderText("e.g. citadel_cloud")
        layout.addRow("Database name:", self.dbname)

        self.user = QLineEdit()
        layout.addRow("User:", self.user)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Password:", self.password)

        self.host = QLineEdit()
        self.host.setPlaceholderText("e.g. db.example.com or 34.xxx.xxx.xxx")
        layout.addRow("Host:", self.host)

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(5432)
        layout.addRow("Port:", self.port)

        self.registerField("cloud_dbname", self.dbname)
        self.registerField("cloud_user", self.user)
        self.registerField("cloud_password", self.password)
        self.registerField("cloud_host", self.host)
        self.registerField("cloud_port", self.port)

        for w in (self.dbname, self.user, self.password, self.host):
            w.textChanged.connect(self.completeChanged)

    def isComplete(self):
        return bool(
            self.dbname.text().strip()
            and self.user.text().strip()
            and self.password.text().strip()
            and self.host.text().strip()
        )

class CloudSslPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Cloud Database SSL (Optional)")
        self.setSubTitle("Cloud SQL and similar services require encrypted connections. Set SSL mode and certificates here.")
        layout = QFormLayout(self)

        self.sslmode = QComboBox()
        self.sslmode.addItems(["require", "verify-ca", "verify-full", "prefer", "disable"])
        self.sslmode.setCurrentText("require")
        self.sslmode.setToolTip("require = encrypted connection (typical for Cloud SQL); verify-ca/verify-full = also verify server cert")
        layout.addRow("SSL mode:", self.sslmode)

        self.sslrootcert = QLineEdit()
        self.sslrootcert.setPlaceholderText("Path to CA certificate (.pem, .crt)")
        btn_root = QPushButton("Browse...")
        btn_root.clicked.connect(lambda: self._browse(self.sslrootcert, "CA certificate"))
        row = QHBoxLayout()
        row.addWidget(self.sslrootcert)
        row.addWidget(btn_root)
        layout.addRow("Root cert:", row)

        self.sslcert = QLineEdit()
        self.sslcert.setPlaceholderText("Path to client certificate (.pem, .crt)")
        btn_cert = QPushButton("Browse...")
        btn_cert.clicked.connect(lambda: self._browse(self.sslcert, "Client certificate"))
        row2 = QHBoxLayout()
        row2.addWidget(self.sslcert)
        row2.addWidget(btn_cert)
        layout.addRow("Client cert:", row2)

        self.sslkey = QLineEdit()
        self.sslkey.setPlaceholderText("Path to client key (.pem, .key)")
        btn_key = QPushButton("Browse...")
        btn_key.clicked.connect(lambda: self._browse(self.sslkey, "Client key"))
        row3 = QHBoxLayout()
        row3.addWidget(self.sslkey)
        row3.addWidget(btn_key)
        layout.addRow("Client key:", row3)

        self.registerField("cloud_sslmode", self.sslmode, "currentText")
        self.registerField("cloud_sslrootcert", self.sslrootcert)
        self.registerField("cloud_sslcert", self.sslcert)
        self.registerField("cloud_sslkey", self.sslkey)

    def _browse(self, line_edit: QLineEdit, title: str):
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {title}",
            "",
            "Certificate files (*.pem *.crt *.cer *.key);;All files (*)",
        )
        if path:
            line_edit.setText(path)

class SmtpPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Email (SMTP)")
        self.setSubTitle("Configure SMTP for sending parent/guardian notifications.")
        layout = QFormLayout(self)

        self.host = QLineEdit()
        self.host.setPlaceholderText("e.g. smtp.gmail.com")
        self.host.setText("smtp.gmail.com")
        layout.addRow("SMTP host:", self.host)

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(587)
        layout.addRow("Port:", self.port)

        self.user = QLineEdit()
        self.user.setPlaceholderText("e.g. your-email@gmail.com")
        layout.addRow("Email / username:", self.user)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("App password (for Gmail, use App Password)")
        layout.addRow("Password:", self.password)

        self.tls = QCheckBox("Use TLS")
        self.tls.setChecked(True)
        layout.addRow("", self.tls)

        self.registerField("smtp_host", self.host)
        self.registerField("smtp_user", self.user)
        self.registerField("smtp_password", self.password)
        self.registerField("smtp_port", self.port)
        self.registerField("smtp_tls", self.tls)

        for w in (self.host, self.user, self.password):
            w.textChanged.connect(self.completeChanged)

    def isComplete(self):
        return bool(
            self.host.text().strip()
            and self.user.text().strip()
            and self.password.text().strip()
        )

class TwilioPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("SMS (Twilio)")
        self.setSubTitle("Configure Twilio for SMS notifications to guardians.")
        layout = QFormLayout(self)

        self.account_sid = QLineEdit()
        self.account_sid.setPlaceholderText("ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        layout.addRow("Account SID:", self.account_sid)

        self.auth_token = QLineEdit()
        self.auth_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.auth_token.setPlaceholderText("Auth token")
        layout.addRow("Auth token:", self.auth_token)

        self.phone_number = QLineEdit()
        self.phone_number.setPlaceholderText("e.g. +1234567890")
        layout.addRow("Twilio phone number:", self.phone_number)

        self.messaging_sid = QLineEdit()
        self.messaging_sid.setPlaceholderText("Messaging Service SID (MG...)")
        layout.addRow("Messaging Service SID:", self.messaging_sid)

        self.registerField("twilio_account_sid", self.account_sid)
        self.registerField("twilio_auth_token", self.auth_token)
        self.registerField("twilio_phone", self.phone_number)
        self.registerField("twilio_messaging_sid", self.messaging_sid)

class FernetKeyPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Biometrics (Fernet Key)")
        self.setSubTitle(
            "Encryption key for face and fingerprint data. "
            "The same key must be set as FERNET_KEY in Cloud Run for mobile verification."
        )
        layout = QVBoxLayout(self)

        self.radio_generate = QRadioButton("Generate new key (recommended for first-time setup)")
        self.radio_existing = QRadioButton("Use existing key (e.g. from Cloud Run)")
        self.radio_generate.setChecked(True)
        layout.addWidget(self.radio_generate)
        layout.addWidget(self.radio_existing)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Paste your Fernet key (e.g. from Cloud Run FERNET_KEY)")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(QLabel("Existing key:"))
        layout.addWidget(self.key_edit)

        self.registerField("fernet_use_existing", self.radio_existing)
        self.registerField("fernet_key", self.key_edit)

        def _toggle():
            self.key_edit.setEnabled(self.radio_existing.isChecked())
            self.completeChanged.emit()
        self.radio_generate.toggled.connect(_toggle)
        self.radio_existing.toggled.connect(_toggle)
        self.key_edit.textChanged.connect(self.completeChanged)
        self.key_edit.setEnabled(False)

    def isComplete(self):
        if self.radio_generate.isChecked():
            return True
        key = (self.key_edit.text() or "").strip()
        if not key:
            return False
        try:
            from cryptography.fernet import Fernet
            Fernet(key.encode() if isinstance(key, str) else key)
            return True
        except Exception:
            return False

    def validatePage(self):
        if self.radio_existing.isChecked():
            key = (self.key_edit.text() or "").strip()
            try:
                from cryptography.fernet import Fernet
                Fernet(key.encode() if isinstance(key, str) else key)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Invalid Key",
                    f"The Fernet key appears invalid: {e}\n\n"
                    "A valid key is 44 characters, base64 URL-safe (e.g. from Fernet.generate_key())."
                )
                return False
        return True

class FinishPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Complete Setup")
        self.setSubTitle("Review and save your configuration.")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Click Finish to save your configuration securely.\n\n"
            "• Passwords and tokens will be stored in your system credential store.\n"
            "• Other settings will be stored in an encrypted file."
        ))

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Citadel Settings")
        self.setMinimumSize(720, 520)

        self._local_existing = get_local_db()
        self._cloud_existing = get_cloud_db()
        self._smtp_existing = get_smtp_config()
        self._twilio_existing = get_twilio_config()
        self._fernet_existing = get_fernet_key()
        self._sync_existing = get_sync_config()
        self._slideshow_existing = get_slideshow_config()
        self._app_existing = get_app_config()

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self._build_local_tab()
        self._build_cloud_tab()
        self._build_cloud_ssl_tab()
        self._build_smtp_tab()
        self._build_twilio_tab()
        self._build_fernet_tab()
        self._build_sync_tab()
        self._build_app_tab()
        self._build_slideshow_tab()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.save_btn = QPushButton("Save")
        self.cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        self.save_btn.clicked.connect(self._on_save)
        self.cancel_btn.clicked.connect(self.reject)

    def _build_local_tab(self):
        tab = QGroupBox()
        form = QFormLayout(tab)
        self.local_dbname = QLineEdit()
        self.local_user = QLineEdit()
        self.local_password = QLineEdit()
        self.local_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.local_password.setPlaceholderText("Leave blank to keep existing")
        self.local_host = QLineEdit()
        self.local_port = QSpinBox()
        self.local_port.setRange(1, 65535)

        form.addRow("Database name:", self.local_dbname)
        form.addRow("User:", self.local_user)
        form.addRow("Password:", self.local_password)
        form.addRow("Host:", self.local_host)
        form.addRow("Port:", self.local_port)

        self.tabs.addTab(tab, "Local DB")

        self.local_dbname.setText(self._local_existing.get("dbname", ""))
        self.local_user.setText(self._local_existing.get("user", ""))
        self.local_host.setText(self._local_existing.get("host", "127.0.0.1"))
        self.local_port.setValue(int(self._local_existing.get("port", 5432) or 5432))

    def _build_cloud_tab(self):
        tab = QGroupBox()
        form = QFormLayout(tab)
        self.cloud_dbname = QLineEdit()
        self.cloud_user = QLineEdit()
        self.cloud_password = QLineEdit()
        self.cloud_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_password.setPlaceholderText("Leave blank to keep existing")
        self.cloud_host = QLineEdit()
        self.cloud_port = QSpinBox()
        self.cloud_port.setRange(1, 65535)

        form.addRow("Database name:", self.cloud_dbname)
        form.addRow("User:", self.cloud_user)
        form.addRow("Password:", self.cloud_password)
        form.addRow("Host:", self.cloud_host)
        form.addRow("Port:", self.cloud_port)

        self.tabs.addTab(tab, "Cloud DB")

        self.cloud_dbname.setText(self._cloud_existing.get("dbname", ""))
        self.cloud_user.setText(self._cloud_existing.get("user", ""))
        self.cloud_host.setText(self._cloud_existing.get("host", ""))
        self.cloud_port.setValue(int(self._cloud_existing.get("port", 5432) or 5432))

    def _build_cloud_ssl_tab(self):
        tab = QGroupBox()
        form = QFormLayout(tab)
        self.cloud_sslmode = QComboBox()
        self.cloud_sslmode.addItems(["require", "verify-ca", "verify-full", "prefer", "disable"])
        self.cloud_sslrootcert = QLineEdit()
        self.cloud_sslcert = QLineEdit()
        self.cloud_sslkey = QLineEdit()

        btn_root = QPushButton("Browse...")
        btn_root.clicked.connect(lambda: self._browse(self.cloud_sslrootcert, "CA certificate"))
        row_root = QHBoxLayout()
        row_root.addWidget(self.cloud_sslrootcert)
        row_root.addWidget(btn_root)

        btn_cert = QPushButton("Browse...")
        btn_cert.clicked.connect(lambda: self._browse(self.cloud_sslcert, "Client certificate"))
        row_cert = QHBoxLayout()
        row_cert.addWidget(self.cloud_sslcert)
        row_cert.addWidget(btn_cert)

        btn_key = QPushButton("Browse...")
        btn_key.clicked.connect(lambda: self._browse(self.cloud_sslkey, "Client key"))
        row_key = QHBoxLayout()
        row_key.addWidget(self.cloud_sslkey)
        row_key.addWidget(btn_key)

        form.addRow("SSL mode:", self.cloud_sslmode)
        form.addRow("Root cert:", row_root)
        form.addRow("Client cert:", row_cert)
        form.addRow("Client key:", row_key)

        self.tabs.addTab(tab, "Cloud SSL")

        self.cloud_sslmode.setCurrentText(self._cloud_existing.get("sslmode", "prefer") or "prefer")
        self.cloud_sslrootcert.setText(self._cloud_existing.get("sslrootcert") or "")
        self.cloud_sslcert.setText(self._cloud_existing.get("sslcert") or "")
        self.cloud_sslkey.setText(self._cloud_existing.get("sslkey") or "")

    def _build_smtp_tab(self):
        tab = QGroupBox()
        form = QFormLayout(tab)
        self.smtp_host = QLineEdit()
        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(1, 65535)
        self.smtp_user = QLineEdit()
        self.smtp_password = QLineEdit()
        self.smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.smtp_password.setPlaceholderText("Leave blank to keep existing")
        self.smtp_tls = QCheckBox("Use TLS")

        form.addRow("SMTP host:", self.smtp_host)
        form.addRow("Port:", self.smtp_port)
        form.addRow("Email / username:", self.smtp_user)
        form.addRow("Password:", self.smtp_password)
        form.addRow("", self.smtp_tls)

        self.tabs.addTab(tab, "Email (SMTP)")

        self.smtp_host.setText(self._smtp_existing.get("host", "smtp.gmail.com"))
        self.smtp_port.setValue(int(self._smtp_existing.get("port", 587) or 587))
        self.smtp_user.setText(self._smtp_existing.get("user", ""))
        self.smtp_tls.setChecked(bool(self._smtp_existing.get("tls", True)))

    def _build_twilio_tab(self):
        tab = QGroupBox()
        form = QFormLayout(tab)
        self.twilio_account_sid = QLineEdit()
        self.twilio_auth_token = QLineEdit()
        self.twilio_auth_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.twilio_auth_token.setPlaceholderText("Leave blank to keep existing")
        self.twilio_phone = QLineEdit()
        self.twilio_messaging_sid = QLineEdit()

        form.addRow("Account SID:", self.twilio_account_sid)
        form.addRow("Auth token:", self.twilio_auth_token)
        form.addRow("Twilio phone number:", self.twilio_phone)
        form.addRow("Messaging Service SID:", self.twilio_messaging_sid)

        self.tabs.addTab(tab, "SMS (Twilio)")

        self.twilio_account_sid.setText(self._twilio_existing.get("account_sid", ""))
        self.twilio_phone.setText(self._twilio_existing.get("phone_number", ""))
        self.twilio_messaging_sid.setText(self._twilio_existing.get("messaging_sid", ""))

    def _build_fernet_tab(self):
        tab = QGroupBox()
        layout = QVBoxLayout(tab)
        self.fernet_keep = QRadioButton("Keep existing key")
        self.fernet_set = QRadioButton("Set new key")
        layout.addWidget(self.fernet_keep)
        layout.addWidget(self.fernet_set)

        row = QHBoxLayout()
        self.fernet_key = QLineEdit()
        self.fernet_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.fernet_key.setPlaceholderText("Paste Fernet key or generate")
        self.fernet_generate = QPushButton("Generate")
        self.fernet_generate.clicked.connect(self._generate_fernet_key)
        row.addWidget(self.fernet_key)
        row.addWidget(self.fernet_generate)
        layout.addWidget(QLabel("Fernet key:"))
        layout.addLayout(row)

        self.tabs.addTab(tab, "Biometrics")

        if self._fernet_existing:
            self.fernet_keep.setChecked(True)
        else:
            self.fernet_set.setChecked(True)
        self._toggle_fernet_fields()
        self.fernet_keep.toggled.connect(self._toggle_fernet_fields)
        self.fernet_set.toggled.connect(self._toggle_fernet_fields)

    def _build_sync_tab(self):
        tab = QGroupBox()
        form = QFormLayout(tab)
        self.sync_interval = QSpinBox()
        self.sync_interval.setRange(10, 86400)
        self.upload_interval = QSpinBox()
        self.upload_interval.setRange(10, 86400)

        self.ref_tables = QLineEdit()
        self.verif_table = QLineEdit()
        self.verif_id_col = QLineEdit()
        self.verif_method_col = QLineEdit()

        self.students_table = QLineEdit()
        self.students_updated_col = QLineEdit()
        self.students_facial_data_col = QLineEdit()
        self.students_facial_flag_col = QLineEdit()

        self.fingerprint_table = QLineEdit()
        self.fingerprint_updated_col = QLineEdit()
        self.fingerprint_template_col = QLineEdit()

        form.addRow("Sync interval (sec):", self.sync_interval)
        form.addRow("Upload interval (sec):", self.upload_interval)
        form.addRow("Reference tables (comma):", self.ref_tables)
        form.addRow("Verification table:", self.verif_table)
        form.addRow("Verification id column:", self.verif_id_col)
        form.addRow("Verification method column:", self.verif_method_col)
        form.addRow("Students table:", self.students_table)
        form.addRow("Students updated_at column:", self.students_updated_col)
        form.addRow("Students facial data column:", self.students_facial_data_col)
        form.addRow("Students facial flag column:", self.students_facial_flag_col)
        form.addRow("Fingerprints table:", self.fingerprint_table)
        form.addRow("Fingerprints updated_at column:", self.fingerprint_updated_col)
        form.addRow("Fingerprints template column:", self.fingerprint_template_col)

        self.tabs.addTab(tab, "Sync")

        self.sync_interval.setValue(int(self._sync_existing.get("sync_interval", 300)))
        self.upload_interval.setValue(int(self._sync_existing.get("upload_interval", 60)))
        self.ref_tables.setText(", ".join(self._sync_existing.get("reference_tables", [])))
        ver = self._sync_existing.get("verification_methods", {})
        self.verif_table.setText(ver.get("table", "verification_methods"))
        self.verif_id_col.setText(ver.get("id_column", "id"))
        self.verif_method_col.setText(ver.get("method_column", "method"))
        students = self._sync_existing.get("students", {})
        self.students_table.setText(students.get("table", "students"))
        self.students_updated_col.setText(students.get("updated_at_column", "updated_at"))
        self.students_facial_data_col.setText(students.get("facial_data_column", "facial_recognition_data"))
        self.students_facial_flag_col.setText(students.get("facial_flag_column", "has_facial_recognition"))
        fingerprints = self._sync_existing.get("fingerprints", {})
        self.fingerprint_table.setText(fingerprints.get("table", "fingerprints"))
        self.fingerprint_updated_col.setText(fingerprints.get("updated_at_column", "updated_at"))
        self.fingerprint_template_col.setText(fingerprints.get("template_column", "template"))

    def _build_slideshow_tab(self):
        tab = QGroupBox()
        layout = QVBoxLayout(tab)

        info = QLabel("Manage slideshow images stored in the cloud. These sync to the local cache on full sync at launch.")
        layout.addWidget(info)

        self.slideshow_list = QListWidget()
        self.slideshow_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.slideshow_list)

        row = QHBoxLayout()
        self.slideshow_refresh = QPushButton("Refresh")
        self.slideshow_add = QPushButton("Upload Images...")
        self.slideshow_delete = QPushButton("Delete Selected")
        row.addWidget(self.slideshow_refresh)
        row.addWidget(self.slideshow_add)
        row.addWidget(self.slideshow_delete)
        row.addStretch()
        layout.addLayout(row)

        interval_row = QFormLayout()
        self.slideshow_interval = QSpinBox()
        self.slideshow_interval.setRange(2, 120)
        interval_row.addRow("Slide interval (sec):", self.slideshow_interval)
        layout.addLayout(interval_row)

        self.tabs.addTab(tab, "Slideshow")

        self.slideshow_interval.setValue(int(self._slideshow_existing.get("interval", 5)))

        self.slideshow_refresh.clicked.connect(lambda: self._load_slideshow_list(show_errors=True))
        self.slideshow_add.clicked.connect(self._upload_slideshow_images)
        self.slideshow_delete.clicked.connect(self._delete_slideshow_images)
        self._load_slideshow_list(show_errors=False)

    def _build_app_tab(self):
        tab = QGroupBox()
        layout = QVBoxLayout(tab)
        self.run_main_on_startup = QCheckBox("Run Citadel Main on Windows startup")
        self.run_main_on_startup.setChecked(bool(self._app_existing.get("run_main_on_startup", False)))
        layout.addWidget(self.run_main_on_startup)
        layout.addStretch()
        self.tabs.addTab(tab, "Application")

    def _startup_shortcut_path(self) -> str:
        startup_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            "Startup",
        )
        return os.path.join(startup_dir, "Citadel Main.cmd")

    def _resolve_main_exe_path(self) -> str | None:
        base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
        candidates = [
            os.path.join(base_dir, "Citadel.exe"),
            os.path.join(base_dir, "Citadel", "Citadel.exe"),
            os.path.join(base_dir, "..", "Citadel.exe"),
        ]
        for candidate in candidates:
            candidate = os.path.abspath(candidate)
            if os.path.exists(candidate):
                return candidate
        return None

    def _apply_startup_setting(self, enabled: bool) -> tuple[bool, str]:
        try:
            shortcut_path = self._startup_shortcut_path()
            if winreg is None:
                return False, "Windows startup registry is unavailable on this platform."

            run_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            run_value_name = "Citadel Main"

            if enabled:
                main_exe = self._resolve_main_exe_path()
                if not main_exe:
                    return False, "Citadel.exe was not found near the settings executable."
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key_path) as key:
                    winreg.SetValueEx(key, run_value_name, 0, winreg.REG_SZ, "\"{}\"".format(main_exe))
                # Remove legacy Startup .cmd entry if present.
                if os.path.exists(shortcut_path):
                    os.remove(shortcut_path)
                return True, ""

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, run_value_name)
            except FileNotFoundError:
                pass
            except OSError:
                pass

            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
            return True, ""
        except Exception as e:
            return False, str(e)

    def _get_cloud_conn_for_slideshow(self, show_errors: bool = True):
        dbname = self.cloud_dbname.text().strip()
        user = self.cloud_user.text().strip()
        host = self.cloud_host.text().strip()
        port = int(self.cloud_port.value())
        password = self.cloud_password.text().strip() or (self._cloud_existing.get("password") or "")
        if not (dbname and user and host and password):
            if show_errors:
                QMessageBox.warning(
                    self,
                    "Cloud Database",
                    "Please enter Cloud DB host, user, database name, and password first.",
                )
            return None

        sslmode = self.cloud_sslmode.currentText() or "require"
        sslrootcert = (self.cloud_sslrootcert.text() or "").strip() or None
        sslcert = (self.cloud_sslcert.text() or "").strip() or None
        sslkey = (self.cloud_sslkey.text() or "").strip() or None
        if sslmode in ("prefer", "disable") and (sslrootcert or sslcert or sslkey):
            sslmode = "require"

        try:
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                host=host,
                port=port,
                sslmode=sslmode,
                sslrootcert=sslrootcert,
                sslcert=sslcert,
                sslkey=sslkey,
            )
            conn.autocommit = True
            return conn
        except Exception as e:
            if show_errors:
                QMessageBox.warning(self, "Cloud Database", f"Unable to connect to cloud DB: {e}")
            return None

    def _load_slideshow_list(self, show_errors: bool = True):
        self.slideshow_list.clear()
        conn = self._get_cloud_conn_for_slideshow(show_errors=show_errors)
        if not conn:
            if not show_errors:
                self.slideshow_list.addItem("Enter cloud DB settings and click Refresh.")
            return
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, octet_length(image) FROM slideshow ORDER BY id")
            rows = cur.fetchall() or []
            if not rows:
                self.slideshow_list.addItem("No images found.")
                return
            for slide_id, size in rows:
                size_kb = (size or 0) / 1024.0
                label = f"ID {slide_id} - {size_kb:.1f} KB"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, slide_id)
                self.slideshow_list.addItem(item)
        except Exception as e:
            if show_errors:
                QMessageBox.warning(self, "Slideshow", f"Unable to load slideshow list: {e}")
            self.slideshow_list.addItem("Unable to load slideshow list.")
        finally:
            cur.close()
            conn.close()

    def _upload_slideshow_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Slideshow Images",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All files (*)",
        )
        if not paths:
            return
        conn = self._get_cloud_conn_for_slideshow(show_errors=True)
        if not conn:
            return
        cur = conn.cursor()
        try:
            payload = []
            for path in paths:
                try:
                    with open(path, "rb") as f:
                        payload.append((Binary(f.read()),))
                except Exception:
                    continue
            if not payload:
                QMessageBox.information(self, "Slideshow", "No valid images were selected.")
                return
            cur.executemany("INSERT INTO slideshow (image) VALUES (%s)", payload)
            QMessageBox.information(self, "Slideshow", "Images uploaded to cloud.")
        except Exception as e:
            QMessageBox.warning(self, "Slideshow", f"Failed to upload images: {e}")
        finally:
            cur.close()
            conn.close()
        self._load_slideshow_list(show_errors=False)

    def _delete_slideshow_images(self):
        items = self.slideshow_list.selectedItems() if hasattr(self, "slideshow_list") else []
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in items if item.data(Qt.ItemDataRole.UserRole)]
        if not ids:
            QMessageBox.information(self, "Slideshow", "Select one or more images to delete.")
            return
        reply = QMessageBox.question(
            self,
            "Delete Images",
            f"Delete {len(ids)} selected image(s) from the cloud slideshow?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        conn = self._get_cloud_conn_for_slideshow(show_errors=True)
        if not conn:
            return
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM slideshow WHERE id = ANY(%s)", (ids,))
            QMessageBox.information(self, "Slideshow", "Selected images deleted.")
        except Exception as e:
            QMessageBox.warning(self, "Slideshow", f"Failed to delete images: {e}")
        finally:
            cur.close()
            conn.close()
        self._load_slideshow_list(show_errors=False)

    def _toggle_fernet_fields(self):
        enabled = self.fernet_set.isChecked()
        self.fernet_key.setEnabled(enabled)
        self.fernet_generate.setEnabled(enabled)

    def _generate_fernet_key(self):
        try:
            from cryptography.fernet import Fernet
            self.fernet_key.setText(Fernet.generate_key().decode())
        except Exception:
            QMessageBox.warning(self, "Fernet", "Unable to generate Fernet key.")

    def _browse(self, line_edit: QLineEdit, title: str):
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {title}",
            "",
            "Certificate files (*.pem *.crt *.cer *.key);;All files (*)",
        )
        if path:
            line_edit.setText(path)

    def _required(self, label: str, value: str) -> bool:
        if value.strip():
            return True
        QMessageBox.warning(self, "Missing Field", f"Please enter {label}.")
        return False

    def _on_save(self):
        if not self._required("Local DB name", self.local_dbname.text()):
            return
        if not self._required("Local DB user", self.local_user.text()):
            return
        if not self._required("Local DB host", self.local_host.text()):
            return
        if not self._required("Cloud DB name", self.cloud_dbname.text()):
            return
        if not self._required("Cloud DB user", self.cloud_user.text()):
            return
        if not self._required("Cloud DB host", self.cloud_host.text()):
            return

        local_password = self.local_password.text().strip() or (self._local_existing.get("password") or "")
        cloud_password = self.cloud_password.text().strip() or (self._cloud_existing.get("password") or "")
        smtp_password = self.smtp_password.text().strip() or (self._smtp_existing.get("password") or "")
        twilio_auth = self.twilio_auth_token.text().strip() or (self._twilio_existing.get("auth_token") or "")

        if not is_configured():
            if not local_password:
                QMessageBox.warning(self, "Missing Field", "Please enter Local DB password.")
                return
            if not cloud_password:
                QMessageBox.warning(self, "Missing Field", "Please enter Cloud DB password.")
                return
            if not smtp_password:
                QMessageBox.warning(self, "Missing Field", "Please enter SMTP password.")
                return

        fernet_key = None
        if self.fernet_set.isChecked():
            fernet_key = (self.fernet_key.text() or "").strip()
            if not fernet_key:
                self._generate_fernet_key()
                fernet_key = (self.fernet_key.text() or "").strip()
            try:
                from cryptography.fernet import Fernet
                Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
            except Exception as e:
                QMessageBox.warning(self, "Invalid Key", f"Invalid Fernet key: {e}")
                return
        else:
            fernet_key = self._fernet_existing or None

        sync_cfg = {
            "sync_interval": int(self.sync_interval.value()),
            "upload_interval": int(self.upload_interval.value()),
            "reference_tables": [t.strip() for t in (self.ref_tables.text() or "").split(",") if t.strip()],
            "verification_methods": {
                "table": (self.verif_table.text() or "").strip() or "verification_methods",
                "id_column": (self.verif_id_col.text() or "").strip() or "id",
                "method_column": (self.verif_method_col.text() or "").strip() or "method",
            },
            "students": {
                "table": (self.students_table.text() or "").strip() or "students",
                "updated_at_column": (self.students_updated_col.text() or "").strip() or "updated_at",
                "facial_data_column": (self.students_facial_data_col.text() or "").strip() or "facial_recognition_data",
                "facial_flag_column": (self.students_facial_flag_col.text() or "").strip() or "has_facial_recognition",
            },
            "fingerprints": {
                "table": (self.fingerprint_table.text() or "").strip() or "fingerprints",
                "updated_at_column": (self.fingerprint_updated_col.text() or "").strip() or "updated_at",
                "template_column": (self.fingerprint_template_col.text() or "").strip() or "template",
            },
        }

        slideshow_cfg = {
            "interval": int(self.slideshow_interval.value()),
        }
        app_cfg = {
            "run_main_on_startup": bool(self.run_main_on_startup.isChecked()),
        }

        local_db = {
            "dbname": self.local_dbname.text().strip(),
            "user": self.local_user.text().strip(),
            "host": self.local_host.text().strip(),
            "port": self.local_port.value(),
        }
        cloud_db = {
            "dbname": self.cloud_dbname.text().strip(),
            "user": self.cloud_user.text().strip(),
            "host": self.cloud_host.text().strip(),
            "port": self.cloud_port.value(),
            "sslmode": self.cloud_sslmode.currentText() or "require",
            "sslrootcert": (self.cloud_sslrootcert.text() or "").strip(),
            "sslcert": (self.cloud_sslcert.text() or "").strip(),
            "sslkey": (self.cloud_sslkey.text() or "").strip(),
        }
        smtp = {
            "host": self.smtp_host.text().strip(),
            "port": self.smtp_port.value(),
            "user": self.smtp_user.text().strip(),
            "tls": self.smtp_tls.isChecked(),
        }
        twilio = {
            "account_sid": self.twilio_account_sid.text().strip(),
            "phone_number": self.twilio_phone.text().strip(),
            "messaging_sid": self.twilio_messaging_sid.text().strip(),
        }

        ok = save_config(
            local_db=local_db,
            local_db_password=local_password,
            cloud_db=cloud_db,
            cloud_db_password=cloud_password,
            smtp=smtp,
            smtp_password=smtp_password,
            twilio=twilio,
            twilio_auth_token=twilio_auth,
            fernet_key=fernet_key,
            sync=sync_cfg,
            slideshow=slideshow_cfg,
            app=app_cfg,
        )
        if ok:
            startup_ok, startup_err = self._apply_startup_setting(bool(self.run_main_on_startup.isChecked()))
            if not startup_ok:
                QMessageBox.warning(
                    self,
                    "Startup Setting",
                    f"Configuration saved, but startup setting could not be applied:\n{startup_err}",
                )
            QMessageBox.information(self, "Settings Saved", "Configuration has been saved.")
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Settings Failed",
                "Failed to save configuration. Please check that keyring is working.",
            )

def run_setup_wizard(parent=None) -> bool:
    from system_checks import check_postgresql_installed
    ok, msg = check_postgresql_installed()
    if not ok:
        QMessageBox.critical(parent, "PostgreSQL Required", msg)
        return False
    if not keyring_available():
        QMessageBox.critical(
            parent,
            "Setup Not Available",
            "The 'keyring' package is required for secure storage.\n\n"
            "Install it with: pip install keyring"
        )
        return False

    dlg = SettingsDialog(parent)
    return dlg.exec() == QDialog.DialogCode.Accepted

if __name__ == "__main__":
    configure_logging("citadel-settings")
    app = QApplication(sys.argv)
    run_setup_wizard()
    sys.exit(0)
