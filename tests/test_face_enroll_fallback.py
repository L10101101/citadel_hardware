import unittest
from unittest.mock import patch

import numpy as np

try:
    import face_enroll_worker as few
    _IMPORT_ERROR = None
except Exception as e:
    few = None
    _IMPORT_ERROR = e


@unittest.skipIf(few is None, f"face_enroll_worker import failed: {_IMPORT_ERROR}")
class TestFaceEnrollFallback(unittest.TestCase):
    def test_cloud_transient_failure_uses_local_fallback(self):
        emb = np.ones(256, dtype=np.float32)
        with patch("face_enroll_worker.save_to_cloud", side_effect=RuntimeError("cloud down")):
            with patch("face_enroll_worker.save_to_db", return_value=None) as save_local:
                ok, msg = few.persist_enrollment_embedding("2024-0001", emb)
        self.assertTrue(ok)
        self.assertEqual(msg, "Saved locally (cloud unavailable)")
        save_local.assert_called_once()

    def test_cloud_student_not_found_fails_without_fallback(self):
        emb = np.ones(256, dtype=np.float32)
        with patch("face_enroll_worker.save_to_cloud", side_effect=ValueError("2024-0001 Not Found")):
            with patch("face_enroll_worker.save_to_db", return_value=None) as save_local:
                ok, msg = few.persist_enrollment_embedding("2024-0001", emb)
        self.assertFalse(ok)
        self.assertIn("Not Found", msg)
        save_local.assert_not_called()


if __name__ == "__main__":
    unittest.main()
