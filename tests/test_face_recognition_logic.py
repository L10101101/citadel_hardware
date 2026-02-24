import unittest
import numpy as np

try:
    import face_recognition as fr
    _IMPORT_ERROR = None
except Exception as e:
    fr = None
    _IMPORT_ERROR = e


@unittest.skipIf(fr is None, f"face_recognition import failed: {_IMPORT_ERROR}")
class TestFaceRecognitionLogic(unittest.TestCase):
    def test_quality_check_face_too_small(self):
        img = np.zeros((40, 40, 3), dtype=np.uint8)
        ok, msg = fr._face_quality_check(img)
        self.assertFalse(ok)
        self.assertEqual(msg, "Face too small")

    def test_quality_check_too_dark(self):
        img = np.zeros((160, 160, 3), dtype=np.uint8)
        ok, msg = fr._face_quality_check(img)
        self.assertFalse(ok)
        self.assertEqual(msg, "Too dark")

    def test_similarity_threshold_mode_selection(self):
        old_verify = fr.VERIFY_SIM_THRESHOLD
        old_identify = fr.IDENTIFY_SIM_THRESHOLD
        try:
            fr.VERIFY_SIM_THRESHOLD = 0.81
            fr.IDENTIFY_SIM_THRESHOLD = 0.69
            self.assertAlmostEqual(fr._similarity_threshold("verify"), 0.81)
            self.assertAlmostEqual(fr._similarity_threshold("identify"), 0.69)
            self.assertAlmostEqual(fr._similarity_threshold("unknown"), 0.81)
        finally:
            fr.VERIFY_SIM_THRESHOLD = old_verify
            fr.IDENTIFY_SIM_THRESHOLD = old_identify

    def test_model_health_missing_spoof(self):
        old_det = fr._det_model
        old_rec = fr._rec_model
        old_spoof = fr._spoof_model
        old_errors = list(fr._model_file_errors)
        try:
            fr._det_model = object()
            fr._rec_model = object()
            fr._spoof_model = None
            fr._model_file_errors = []
            ok, msg = fr.get_model_health()
            self.assertFalse(ok)
            self.assertEqual(msg, "Liveness model unavailable")
        finally:
            fr._det_model = old_det
            fr._rec_model = old_rec
            fr._spoof_model = old_spoof
            fr._model_file_errors = old_errors


if __name__ == "__main__":
    unittest.main()
