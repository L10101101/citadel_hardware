import os
import json
import base64
from pathlib import Path

from cryptography.fernet import Fernet

SERVICE_NAME = "Citadel"
CONFIG_KEY_NAME = "config_key"
CONFIG_FILENAME = "config.enc"
KEY_LOCAL_DB_PASSWORD = "local_db_password"
KEY_CLOUD_DB_PASSWORD = "cloud_db_password"
KEY_SMTP_PASSWORD = "smtp_password"
KEY_TWILIO_AUTH_TOKEN = "twilio_auth_token"
KEY_CRYPT_FERNET = "crypt_fernet_key"

def _get_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    path = Path(base) / "Citadel"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(__file__).resolve().parent / ".citadel"
        path.mkdir(parents=True, exist_ok=True)
    return path

def _get_config_path() -> Path:
    return _get_config_dir() / CONFIG_FILENAME

def _get_keyring():
    try:
        import keyring
        return keyring
    except ImportError:
        return None

def _get_config_key() -> bytes | None:
    kr = _get_keyring()
    if not kr:
        return None
    val = kr.get_password(SERVICE_NAME, CONFIG_KEY_NAME)
    if not val:
        return None
    try:
        return val.encode() if isinstance(val, str) else val
    except Exception:
        return None

def _set_config_key(key: bytes) -> bool:
    kr = _get_keyring()
    if not kr:
        return False
    try:
        kr.set_password(SERVICE_NAME, CONFIG_KEY_NAME, key.decode() if isinstance(key, bytes) else key)
        return True
    except Exception:
        return False

def _get_encrypted_config() -> dict | None:
    path = _get_config_path()
    if not path.exists():
        return None
    config_key = _get_config_key()
    if not config_key:
        return None
    try:
        cipher = Fernet(config_key)
        with open(path, "rb") as f:
            encrypted = f.read()
        decrypted = cipher.decrypt(encrypted)
        return json.loads(decrypted.decode())
    except Exception:
        return None

def _save_encrypted_config(data: dict) -> bool:
    config_key = _get_config_key()
    if not config_key:
        return False
    try:
        cipher = Fernet(config_key)
        plain = json.dumps(data, indent=2).encode()
        encrypted = cipher.encrypt(plain)
        path = _get_config_path()
        with open(path, "wb") as f:
            f.write(encrypted)
        return True
    except Exception:
        return False

def _get_secret(key_name: str) -> str | None:
    kr = _get_keyring()
    if not kr:
        return None
    return kr.get_password(SERVICE_NAME, key_name)

def _set_secret(key_name: str, value: str) -> bool:
    kr = _get_keyring()
    if not kr:
        return False
    try:
        kr.set_password(SERVICE_NAME, key_name, value)
        return True
    except Exception:
        return False

def is_configured() -> bool:
    config = _get_encrypted_config()
    if not config:
        return False
    local = config.get("local_db", {})
    if not local.get("dbname") or not local.get("host"):
        return False
    local_pwd = _get_secret(KEY_LOCAL_DB_PASSWORD)
    if not local_pwd:
        return False
    cloud = config.get("cloud_db", {})
    if not cloud.get("host"):
        return False
    cloud_pwd = _get_secret(KEY_CLOUD_DB_PASSWORD)
    if not cloud_pwd:
        return False
    fernet = _get_secret(KEY_CRYPT_FERNET)
    return fernet is not None and len(fernet) > 0

def get_local_db() -> dict:
    config = _get_encrypted_config() or {}
    local = config.get("local_db", {})
    password = _get_secret(KEY_LOCAL_DB_PASSWORD) or ""
    return {
        "dbname": local.get("dbname", ""),
        "user": local.get("user", ""),
        "password": password,
        "host": local.get("host", "127.0.0.1"),
        "port": local.get("port", "5432"),
    }

def get_cloud_db() -> dict:
    config = _get_encrypted_config() or {}
    cloud = config.get("cloud_db", {})
    password = _get_secret(KEY_CLOUD_DB_PASSWORD) or ""
    port = cloud.get("port", "5432")
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 5432
    sslmode = cloud.get("sslmode") or "prefer"
    sslrootcert = cloud.get("sslrootcert") or None
    sslcert = cloud.get("sslcert") or None
    sslkey = cloud.get("sslkey") or None
    if sslmode in ("prefer", "disable") and (sslrootcert or sslcert or sslkey):
        sslmode = "require"
    return {
        "dbname": cloud.get("dbname", ""),
        "user": cloud.get("user", ""),
        "password": password,
        "host": cloud.get("host", ""),
        "port": port,
        "sslmode": sslmode,
        "sslrootcert": sslrootcert,
        "sslcert": sslcert,
        "sslkey": sslkey,
    }

def get_smtp_config() -> dict:
    config = _get_encrypted_config() or {}
    smtp = config.get("smtp", {})
    password = _get_secret(KEY_SMTP_PASSWORD) or ""
    return {
        "host": smtp.get("host", "smtp.gmail.com"),
        "port": smtp.get("port", 587),
        "user": smtp.get("user", ""),
        "password": password,
        "tls": smtp.get("tls", True),
    }

def get_twilio_config() -> dict:
    config = _get_encrypted_config() or {}
    twilio = config.get("twilio", {})
    auth_token = _get_secret(KEY_TWILIO_AUTH_TOKEN) or ""
    return {
        "account_sid": twilio.get("account_sid", ""),
        "auth_token": auth_token,
        "phone_number": twilio.get("phone_number", ""),
        "messaging_sid": twilio.get("messaging_sid", ""),
    }

def get_fernet_key() -> str | None:
    return _get_secret(KEY_CRYPT_FERNET)

def save_config(
    local_db: dict,
    local_db_password: str,
    cloud_db: dict,
    cloud_db_password: str,
    smtp: dict,
    smtp_password: str,
    twilio: dict,
    twilio_auth_token: str,
    fernet_key: str | None = None,
) -> bool:

    kr = _get_keyring()
    if not kr:
        return False

    config_key = _get_config_key()
    if not config_key:
        config_key = Fernet.generate_key()
        if not _set_config_key(config_key):
            return False

    config = {
        "local_db": {
            "dbname": local_db.get("dbname", ""),
            "user": local_db.get("user", ""),
            "host": local_db.get("host", "127.0.0.1"),
            "port": str(local_db.get("port", "5432")),
        },
        "cloud_db": {
            "dbname": cloud_db.get("dbname", ""),
            "user": cloud_db.get("user", ""),
            "host": cloud_db.get("host", ""),
            "port": str(cloud_db.get("port", "5432")),
            "sslmode": cloud_db.get("sslmode", "prefer"),
            "sslrootcert": cloud_db.get("sslrootcert") or "",
            "sslcert": cloud_db.get("sslcert") or "",
            "sslkey": cloud_db.get("sslkey") or "",
        },
        "smtp": {
            "host": smtp.get("host", "smtp.gmail.com"),
            "port": int(smtp.get("port", 587)),
            "user": smtp.get("user", ""),
            "tls": bool(smtp.get("tls", True)),
        },
        "twilio": {
            "account_sid": twilio.get("account_sid", ""),
            "phone_number": twilio.get("phone_number", ""),
            "messaging_sid": twilio.get("messaging_sid", ""),
        },
    }

    if not _set_secret(KEY_LOCAL_DB_PASSWORD, local_db_password or ""):
        return False
    if not _set_secret(KEY_CLOUD_DB_PASSWORD, cloud_db_password or ""):
        return False
    if not _set_secret(KEY_SMTP_PASSWORD, smtp_password or ""):
        return False
    if not _set_secret(KEY_TWILIO_AUTH_TOKEN, twilio_auth_token or ""):
        return False

    if fernet_key:
        key_to_store = fernet_key
    else:
        key_to_store = Fernet.generate_key().decode()
    if not _set_secret(KEY_CRYPT_FERNET, key_to_store):
        return False

    return _save_encrypted_config(config)

def keyring_available() -> bool:
    return _get_keyring() is not None