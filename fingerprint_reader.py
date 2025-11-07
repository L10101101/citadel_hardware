import os
from time import sleep
from pyzkfp import ZKFP2
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from db_utils import get_connection

load_dotenv()
FERNET_KEY = os.getenv("CRYPT_FERNET_KEY")
cipher = Fernet(FERNET_KEY)


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
            print("[DEBUG] No fingerprint captured.")
            return None

        conn, source = get_connection()
        if not conn:
            print("[DEBUG] Connection failed — cannot read fingerprints.")
            return None

        print(f"[DEBUG] Connected to {source.upper()} database")

        cur = conn.cursor()
        try:
            cur.execute("SELECT student_no, template FROM fingerprints")
            records = cur.fetchall()
        except Exception as e:
            print(f"[DEBUG] Database query failed: {e}")
            cur.close()
            conn.close()
            return None

        cur.close()
        conn.close()

        if not records:
            print(f"[DEBUG] No fingerprints found in {source} DB.")
            return None

        print(f"[DEBUG] Retrieved {len(records)} fingerprint records from {source} DB.")

        for student_no, encrypted_template in records:
            try:
                if isinstance(encrypted_template, memoryview):
                    encrypted_template = encrypted_template.tobytes()

                decrypted_template = cipher.decrypt(encrypted_template)
                score = self.zk.DBMatch(template_bytes, decrypted_template)
                print(f"[DEBUG] Compared with {student_no}: score={score}")

                if score >= threshold:
                    print(f"[DEBUG] Match found for {student_no} ✅")
                    return student_no

            except Exception as e:
                print(f"[DEBUG] Error decrypting or matching {student_no}: {e}")

        print("[DEBUG] No matching fingerprint found.")
        return None

    def close(self):
        if self.dev_handle:
            self.zk.CloseDevice()
            self.dev_handle = None
        self.zk.Terminate()
