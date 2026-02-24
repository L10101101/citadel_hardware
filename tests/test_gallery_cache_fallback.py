import unittest
import numpy as np

from unittest.mock import patch

try:
    import face_recognition as fr
    _IMPORT_ERROR = None
except Exception as e:
    fr = None
    _IMPORT_ERROR = e


@unittest.skipIf(fr is None, f"face_recognition import failed: {_IMPORT_ERROR}")
class TestGalleryCacheFallback(unittest.TestCase):
    def test_stale_cache_is_used_when_db_read_fails(self):
        old_cache = fr._gallery_cache
        old_emb = fr._gallery_embeddings
        old_nos = fr._gallery_student_nos
        old_loaded = fr._gallery_loaded_at
        old_ttl = fr.GALLERY_TTL_SECONDS
        try:
            emb = np.ones((256,), dtype=np.float32)
            emb /= np.linalg.norm(emb) + 1e-9
            fr._gallery_cache = {"S-1": {"embedding": emb}}
            fr._gallery_embeddings = np.stack([emb], axis=0).astype(np.float32)
            fr._gallery_student_nos = ["S-1"]
            fr._gallery_loaded_at = 0.0
            fr.GALLERY_TTL_SECONDS = 1

            with patch("face_recognition.get_connection", side_effect=RuntimeError("db down")):
                gallery = fr.load_gallery(force_reload=False)

            self.assertIsNotNone(gallery)
            self.assertIn("S-1", gallery)
        finally:
            fr._gallery_cache = old_cache
            fr._gallery_embeddings = old_emb
            fr._gallery_student_nos = old_nos
            fr._gallery_loaded_at = old_loaded
            fr.GALLERY_TTL_SECONDS = old_ttl

    def test_force_reload_with_db_failure_keeps_existing_cache(self):
        old_cache = fr._gallery_cache
        old_emb = fr._gallery_embeddings
        old_nos = fr._gallery_student_nos
        old_loaded = fr._gallery_loaded_at
        old_ttl = fr.GALLERY_TTL_SECONDS
        try:
            emb = np.ones((256,), dtype=np.float32)
            emb /= np.linalg.norm(emb) + 1e-9
            fr._gallery_cache = {"S-2": {"embedding": emb}}
            fr._gallery_embeddings = np.stack([emb], axis=0).astype(np.float32)
            fr._gallery_student_nos = ["S-2"]
            fr._gallery_loaded_at = 0.0
            fr.GALLERY_TTL_SECONDS = 300

            with patch("face_recognition.get_connection", side_effect=RuntimeError("db down")):
                gallery = fr.load_gallery(force_reload=True)

            self.assertIsNotNone(gallery)
            self.assertIn("S-2", gallery)
        finally:
            fr._gallery_cache = old_cache
            fr._gallery_embeddings = old_emb
            fr._gallery_student_nos = old_nos
            fr._gallery_loaded_at = old_loaded
            fr.GALLERY_TTL_SECONDS = old_ttl


if __name__ == "__main__":
    unittest.main()
