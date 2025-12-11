import psycopg2
import os
import socket
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# DATABASE CONFIGURATION
# -------------------------
LOCAL_DB = {
    "dbname": os.getenv("LOCAL_DBNAME"),
    "user": os.getenv("LOCAL_USER"),
    "password": os.getenv("LOCAL_PASSWORD"),
    "host": os.getenv("LOCAL_HOST"),
    "port": os.getenv("LOCAL_PORT"),
}

CLOUD_DB = {
    "dbname": os.getenv("CLOUD_DBNAME"),
    "user": os.getenv("CLOUD_USER"),
    "password": os.getenv("CLOUD_PASSWORD"),
    "host": os.getenv("CLOUD_HOST"),
    "port": int(os.getenv("CLOUD_PORT")),
    "sslmode": "disable",
    "sslrootcert": os.getenv("SSLROOTCERT"),
    "sslcert": os.getenv("SSLCERT"),
    "sslkey": os.getenv("SSLKEY"),
}


# -------------------------
# CONNECTION CHECKS
# -------------------------
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
    except Exception as e:
        return False


# -------------------------
# CLOUD CONNECTION (writes / authoritative reads)
# -------------------------
def get_cloud_connection():
    if not has_internet():
        raise ConnectionError("No internet connection to cloud")

    if not can_connect(CLOUD_DB["host"], CLOUD_DB["port"]):
        raise ConnectionError("Cloud host unreachable")

    try:
        conn = psycopg2.connect(**CLOUD_DB)
        conn.autocommit = True
        return conn, "cloud"
    except Exception as e:
        raise ConnectionError(f"Cloud connection failed: {e}")


# -------------------------
# LOCAL CONNECTION (read-only)
# -------------------------
def get_local_connection():
    if not can_connect(LOCAL_DB["host"], int(LOCAL_DB["port"])):
        raise ConnectionError("Local host unreachable")

    try:
        conn = psycopg2.connect(**LOCAL_DB)
        conn.set_session(readonly=True, autocommit=True)
        return conn, "local"
    except Exception as e:
        raise ConnectionError(f"Local connection failed: {e}")


# -------------------------
# ROUTER
# -------------------------
def get_connection(mode):
    if mode == "cloud":
        return get_cloud_connection()
    elif mode == "local":
        return get_local_connection()
    else:
        raise ValueError("Invalid mode. Choose 'cloud' or 'local'")
