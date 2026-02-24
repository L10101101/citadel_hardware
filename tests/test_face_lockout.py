import unittest

from face_lockout import FaceLockoutGuard


class TestFaceLockoutGuard(unittest.TestCase):
    def test_triggers_lockout_after_threshold_failures(self):
        guard = FaceLockoutGuard(trigger_count=3, lockout_seconds=2.0, notice_interval_seconds=0.5)
        now = 100.0
        self.assertFalse(guard.register_result(False, now))
        self.assertFalse(guard.register_result(False, now + 0.1))
        self.assertTrue(guard.register_result(False, now + 0.2))
        self.assertTrue(guard.in_lockout(now + 0.3))
        self.assertFalse(guard.in_lockout(now + 2.3))

    def test_success_resets_fail_streak(self):
        guard = FaceLockoutGuard(trigger_count=3, lockout_seconds=2.0)
        self.assertFalse(guard.register_result(False, 1.0))
        self.assertEqual(guard.fail_streak, 1)
        self.assertFalse(guard.register_result(True, 1.1))
        self.assertEqual(guard.fail_streak, 0)

    def test_notice_interval(self):
        guard = FaceLockoutGuard(trigger_count=2, lockout_seconds=2.0, notice_interval_seconds=0.8)
        guard.register_result(False, 10.0)
        guard.register_result(False, 10.1)
        self.assertFalse(guard.should_emit_notice(10.2))
        self.assertTrue(guard.should_emit_notice(10.95))
        self.assertFalse(guard.should_emit_notice(11.0))

    def test_reset_clears_state(self):
        guard = FaceLockoutGuard(trigger_count=2, lockout_seconds=2.0)
        guard.register_result(False, 10.0)
        guard.register_result(False, 10.1)
        self.assertTrue(guard.in_lockout(10.2))
        guard.reset()
        self.assertFalse(guard.in_lockout(10.2))
        self.assertEqual(guard.fail_streak, 0)
        self.assertEqual(guard.last_notice_at, 0.0)


if __name__ == "__main__":
    unittest.main()
