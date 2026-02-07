import sys

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
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from config_store import save_config, keyring_available

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

    wizard = QWizard(parent)
    wizard.setWindowTitle("Citadel Setup")
    wizard.setMinimumSize(500, 400)
    wizard.addPage(WelcomePage())
    wizard.addPage(LocalDbPage())
    wizard.addPage(CloudDbPage())
    wizard.addPage(CloudSslPage())
    wizard.addPage(SmtpPage())
    wizard.addPage(TwilioPage())
    wizard.addPage(FernetKeyPage())
    wizard.addPage(FinishPage())

    if wizard.exec() != QWizard.DialogCode.Accepted:
        return False

    local_db = {
        "dbname": wizard.field("local_dbname"),
        "user": wizard.field("local_user"),
        "host": wizard.field("local_host"),
        "port": wizard.field("local_port"),
    }
    local_password = wizard.field("local_password")

    cloud_db = {
        "dbname": wizard.field("cloud_dbname"),
        "user": wizard.field("cloud_user"),
        "host": wizard.field("cloud_host"),
        "port": wizard.field("cloud_port"),
        "sslmode": wizard.field("cloud_sslmode") or "require",
        "sslrootcert": (wizard.field("cloud_sslrootcert") or "").strip(),
        "sslcert": (wizard.field("cloud_sslcert") or "").strip(),
        "sslkey": (wizard.field("cloud_sslkey") or "").strip(),
    }
    cloud_password = wizard.field("cloud_password")

    smtp = {
        "host": wizard.field("smtp_host"),
        "port": wizard.field("smtp_port"),
        "user": wizard.field("smtp_user"),
        "tls": wizard.field("smtp_tls"),
    }
    smtp_password = wizard.field("smtp_password")

    twilio = {
        "account_sid": wizard.field("twilio_account_sid"),
        "phone_number": wizard.field("twilio_phone"),
        "messaging_sid": wizard.field("twilio_messaging_sid"),
    }
    twilio_auth_token = wizard.field("twilio_auth_token")

    fernet_key = None
    if wizard.field("fernet_use_existing"):
        fernet_key = (wizard.field("fernet_key") or "").strip()
        if not fernet_key:
            fernet_key = None

    ok = save_config(
        local_db=local_db,
        local_db_password=local_password,
        cloud_db=cloud_db,
        cloud_db_password=cloud_password,
        smtp=smtp,
        smtp_password=smtp_password,
        twilio=twilio,
        twilio_auth_token=twilio_auth_token,
        fernet_key=fernet_key,
    )

    if ok:
        from config_store import get_fernet_key
        key = get_fernet_key()
        msg = "Configuration has been saved securely.\n\nYou can now start Citadel."
        if key:
            msg += (
                "\n\n⚠ Save your Fernet key for Cloud Run:\n"
                "Set FERNET_KEY in Cloud Run to the same value.\n"
                "Run: keyring get Citadel crypt_fernet_key (to retrieve it later)"
            )
        QMessageBox.information(parent, "Setup Complete", msg)
        return True
    else:
        QMessageBox.critical(
            parent,
            "Setup Failed",
            "Failed to save configuration. Please check that keyring is working."
        )
        return False

if __name__ == "__main__":
    app = QApplication(sys.argv)
    run_setup_wizard()
    sys.exit(0)