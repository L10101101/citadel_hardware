import unittest
import config_store
from unittest.mock import patch

from cryptography.fernet import Fernet


class TestConfigValidation(unittest.TestCase):
    def test_validate_runtime_config_missing_fields(self):
        with patch("config_store._get_encrypted_config", return_value={}):
            with patch("config_store._get_secret", return_value=None):
                ok, msg = config_store.validate_runtime_config()
        self.assertFalse(ok)
        self.assertIn("Configuration is incomplete or invalid", msg)
        self.assertIn("Local DB name", msg)
        self.assertIn("Cloud DB host", msg)
        self.assertIn("Fernet key", msg)

    def test_validate_runtime_config_invalid_fernet(self):
        cfg = {
            "local_db": {"dbname": "a", "user": "u", "host": "127.0.0.1"},
            "cloud_db": {"dbname": "b", "user": "u", "host": "db.example.com"},
        }

        def fake_secret(name: str):
            if name == config_store.KEY_LOCAL_DB_PASSWORD:
                return "pw1"
            if name == config_store.KEY_CLOUD_DB_PASSWORD:
                return "pw2"
            if name == config_store.KEY_CRYPT_FERNET:
                return "not-a-valid-fernet-key"
            return None

        with patch("config_store._get_encrypted_config", return_value=cfg):
            with patch("config_store._get_secret", side_effect=fake_secret):
                ok, msg = config_store.validate_runtime_config()
        self.assertFalse(ok)
        self.assertIn("Fernet key format is invalid", msg)

    def test_validate_runtime_config_success(self):
        cfg = {
            "local_db": {"dbname": "a", "user": "u", "host": "127.0.0.1"},
            "cloud_db": {"dbname": "b", "user": "u", "host": "db.example.com"},
        }
        valid_fernet = Fernet.generate_key().decode()

        def fake_secret(name: str):
            if name == config_store.KEY_LOCAL_DB_PASSWORD:
                return "pw1"
            if name == config_store.KEY_CLOUD_DB_PASSWORD:
                return "pw2"
            if name == config_store.KEY_CRYPT_FERNET:
                return valid_fernet
            return None

        with patch("config_store._get_encrypted_config", return_value=cfg):
            with patch("config_store._get_secret", side_effect=fake_secret):
                ok, msg = config_store.validate_runtime_config()
        self.assertTrue(ok)
        self.assertEqual(msg, "")


if __name__ == "__main__":
    unittest.main()
