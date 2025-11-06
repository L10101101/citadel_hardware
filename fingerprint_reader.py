import os
import psycopg2
from time import sleep
from pyzkfp import ZKFP2
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from psycopg2 import Binary

load_dotenv()

DB_CONFIG = {
    "dbname": "citadel_db",
    "user": "postgres",
    "password": "postgres",
    "host": "127.0.0.1",
    "port": 5432
}

FERNET_KEY = os.getenv("CRYPT_FERNET_KEY")
cipher = Fernet(FERNET_KEY)


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


class FingerprintReader:
    def __init__(self):
        self.zk = ZKFP2()
        self.zk.Init()

        if self.zk.GetDeviceCount() <= 0:
            raise RuntimeError("Device Missing")

        self.dev_handle = self.zk.OpenDevice()

    def capture_template(self, max_attempts=5):
        for attempt in range(max_attempts):
            try:
                result = self.zk.AcquireFingerprint()
                if result:
                    template, img = result
                    return bytes(template)
            except Exception:
                pass
            sleep(0.5)
        return None

    def identify(self, template_bytes, threshold: int = 80):
        if not template_bytes:
            return None

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT student_no, template FROM fingerprints")
        records = cur.fetchall()
        cur.close()
        conn.close()

        for student_no, encrypted_template in records:
            if isinstance(encrypted_template, memoryview):
                encrypted_template = encrypted_template.tobytes()

            try:
                stored_template = cipher.decrypt(encrypted_template)
                score = self.zk.DBMatch(template_bytes, stored_template)
            except Exception as e:
                continue

            if score >= threshold:
                return student_no
        return None

    def close(self):
        if self.dev_handle:
            self.zk.CloseDevice()
            self.dev_handle = None
        self.zk.Terminate()
