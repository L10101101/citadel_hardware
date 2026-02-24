import unittest

from data_sync import DataSyncManager


class TestDataSyncRetry(unittest.TestCase):
    def test_upload_pending_logs_persists_when_max_retry_reached(self):
        mgr = DataSyncManager()
        mgr._retry_failed_uploads = lambda: None

        saved = []
        mgr._save_failed_upload = lambda data: saved.append(data)
        mgr._upload_log_entry = lambda data: False

        op = {
            "type": "log_entry",
            "data": {"student_no": "S1", "log_type": "entry"},
            "retry_count": 5,
        }
        mgr.sync_queue.queue.put(op)

        mgr._upload_pending_logs()

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["student_no"], "S1")
        self.assertEqual(mgr.sync_queue.size(), 0)

    def test_upload_pending_logs_retries_then_persists(self):
        mgr = DataSyncManager()
        mgr._retry_failed_uploads = lambda: None

        attempts = {"count": 0}
        saved = []

        def always_fail(_data):
            attempts["count"] += 1
            return False

        mgr._upload_log_entry = always_fail
        mgr._save_failed_upload = lambda data: saved.append(data)

        op = {
            "type": "log_entry",
            "data": {"student_no": "S2", "log_type": "entry"},
            "retry_count": 0,
        }
        mgr.sync_queue.queue.put(op)

        mgr._upload_pending_logs()

        self.assertEqual(attempts["count"], 6)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["student_no"], "S2")
        self.assertEqual(mgr.sync_queue.size(), 0)


if __name__ == "__main__":
    unittest.main()
