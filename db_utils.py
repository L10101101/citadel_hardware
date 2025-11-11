import psycopg2, os
import socket
from dotenv import load_dotenv

load_dotenv()

LOCAL_DB = {
    "dbname": "citadel_db",
    "user": "postgres",
    "password": "postgres",
    "host": "127.0.0.1",
    "port": 5432,
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

def has_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False
    
def get_connection():
    if has_internet():
        try:
            conn = psycopg2.connect(**CLOUD_DB)
            return conn, "cloud"
        except psycopg2.OperationalError as e:
            print("[DB] Cloud connection failed. Details:", e)
        except Exception as e:
            print("[DB] DB error:", e)
    else:
        print("[DB] No Internet")

    conn = psycopg2.connect(**LOCAL_DB)
    return conn, "local"
