import os
import sys
from time import sleep
import logging
from cryptography.fernet import Fernet
from db_utils import get_connection
from config_store import get_fernet_key

logger = logging.getLogger(__name__)

def _load_zkfp2():
    # Ensure native SDK paths are visible before loading pyzkfp/pythonnet assembly.
    candidate_dirs = [
        r"C:\Program Files (x86)\FPSensor\Biokey\ZKFPSensors",
        r"C:\Program Files (x86)\FPSensor\Biokey",
    ]
    for d in candidate_dirs:
        if os.path.isdir(d):
            try:
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(d)
            except Exception:
                pass
            if d not in sys.path:
                sys.path.append(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    from pyzkfp import ZKFP2  # defer import until DLL search paths are configured
    return ZKFP2

def _get_cipher():
    key = get_fernet_key()
    if not key:
        raise ValueError("Fernet key not configured.")
    return Fernet(key.encode() if isinstance(key, str) else key)

class FingerprintReader:
    def __init__(self):
        ZKFP2 = _load_zkfp2()
        self.zk = ZKFP2()
        self.zk.Init()
        if self.zk.GetDeviceCount() <= 0:
            raise RuntimeError("Device Missing")
        self.dev_handle = self.zk.OpenDevice()

    def capture_template(self, max_attempts=5):
        last_error = None
        for attempt in range(max_attempts):
            try:
                result = self.zk.AcquireFingerprint()
                if result:
                    template, img = result
                    return bytes(template)
            except Exception as e:
                last_error = e
            sleep(0.5)
        if last_error is not None:
            raise RuntimeError("Fingerprint capture failed") from last_error
        return None

    def is_connected(self) -> bool:
        try:
            if not self.dev_handle:
                return False
            return self.zk.GetDeviceCount() > 0
        except Exception:
            return False

    def identify(self, template_bytes, threshold: int = 80):
        if not template_bytes:
            return None

        conn, source = get_connection("local")
        if not conn:
            return None
        cur = conn.cursor()
        try:
            cur.execute("SELECT student_no, template FROM fingerprints")
            records = cur.fetchall()
        except Exception as e:
            cur.close()
            conn.close()
            return None
        cur.close()
        conn.close()

        if not records:
            return None

        cipher = _get_cipher()
        for student_no, encrypted_template in records:
            try:
                if isinstance(encrypted_template, memoryview):
                    encrypted_template = encrypted_template.tobytes()
                decrypted_template = cipher.decrypt(encrypted_template)
                score = self.zk.DBMatch(template_bytes, decrypted_template)
                if score >= threshold:
                    return student_no
            except Exception as e:
                logger.warning("Fingerprint match skipped for student %s: %s", student_no, e)

        return None

    def close(self):
        if self.dev_handle:
            self.zk.CloseDevice()
        self.dev_handle = None
        self.zk.Terminate()
