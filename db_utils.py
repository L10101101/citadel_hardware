import psycopg2
import socket

from config_store import get_local_db, get_cloud_db


class _DBConfigProxy:
    def __init__(self, getter):
        self._getter = getter

    def get(self, key, default=None):
        return self._getter().get(key, default)

LOCAL_DB = _DBConfigProxy(get_local_db)
CLOUD_DB = _DBConfigProxy(get_cloud_db)


def has_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except Exception:
        return False


def can_connect(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except Exception:
        return False

CONNECT_TIMEOUT_SEC = 15
APP_DB_TIMEZONE = "Asia/Manila"


def get_cloud_connection():
    if not has_internet():
        raise ConnectionError("No internet connection to cloud")
    cloud = get_cloud_db()
    if not can_connect(cloud["host"], cloud["port"]):
        raise ConnectionError("Cloud host unreachable")
    try:
        kwargs = dict(cloud)
        kwargs.setdefault("connect_timeout", CONNECT_TIMEOUT_SEC)
        conn = psycopg2.connect(**kwargs)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f"SET TIME ZONE '{APP_DB_TIMEZONE}'")
        cur.close()
        return conn, "cloud"
    except Exception as e:
        raise ConnectionError(f"Cloud connection failed: {e}")


def get_local_connection():
    local = get_local_db()
    if not can_connect(local["host"], int(local["port"])):
        raise ConnectionError("Local host unreachable")
    try:
        kwargs = dict(local)
        kwargs.setdefault("connect_timeout", CONNECT_TIMEOUT_SEC)
        conn = psycopg2.connect(**kwargs)
        conn.set_session(readonly=False, autocommit=True)
        cur = conn.cursor()
        cur.execute(f"SET TIME ZONE '{APP_DB_TIMEZONE}'")
        cur.close()
        return conn, "local"
    except Exception as e:
        raise ConnectionError(f"Local connection failed: {e}")


def get_connection(mode):
    if mode == "cloud":
        return get_cloud_connection()
    elif mode == "local":
        return get_local_connection()
    else:
        raise ValueError("Invalid mode. Choose 'cloud' or 'local'")
