import psycopg2
from psycopg2 import Binary
from fingerprint_reader import FingerprintReader
from time import sleep
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import os


DB_CONFIG = {
    "dbname": "citadel_db",
    "user": "postgres",
    "password": "postgres",
    "host": "127.0.0.1",
    "port": 5432
}


load_dotenv()
MAX_CAPTURE_ATTEMPTS = 5
FERNET_KEY = os.getenv("CRYPT_FERNET_KEY")
cipher = Fernet(FERNET_KEY)


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def encrypt_template(template: bytes) -> bytes:
    return cipher.encrypt(template)


def save_to_db(student_no: str, template: bytes):
    conn = get_connection()
    cur = conn.cursor()

    encrypted_template = encrypt_template(template)

    cur.execute("""
        INSERT INTO fingerprints (student_no, template)
        VALUES (%s, %s)
        ON CONFLICT (student_no)
        DO UPDATE SET template = EXCLUDED.template
    """, (student_no, Binary(encrypted_template)))

    conn.commit()
    cur.close()
    conn.close()


def capture_fingerprint(reader: FingerprintReader) -> bytes:
    for attempt in range(1, MAX_CAPTURE_ATTEMPTS + 1):
        template = reader.capture_template()
        if template:
            return template
        sleep(1)
    raise RuntimeError("Failed")