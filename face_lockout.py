class FaceLockoutGuard:
    def __init__(
        self,
        trigger_count: int = 24,
        lockout_seconds: float = 2.0,
        notice_interval_seconds: float = 0.8,
    ):
        self.trigger_count = max(1, int(trigger_count))
        self.lockout_seconds = max(0.1, float(lockout_seconds))
        self.notice_interval_seconds = max(0.1, float(notice_interval_seconds))
        self.fail_streak = 0
        self.lockout_until = 0.0
        self.last_notice_at = 0.0

    def reset(self) -> None:
        self.fail_streak = 0
        self.lockout_until = 0.0
        self.last_notice_at = 0.0

    def in_lockout(self, now: float) -> bool:
        return float(now) < self.lockout_until

    def should_emit_notice(self, now: float) -> bool:
        now = float(now)
        if (now - self.last_notice_at) >= self.notice_interval_seconds:
            self.last_notice_at = now
            return True
        return False

    def register_result(self, ok: bool, now: float) -> bool:
        now = float(now)
        if ok:
            self.fail_streak = 0
            return False
        self.fail_streak += 1
        if self.fail_streak >= self.trigger_count:
            self.lockout_until = now + self.lockout_seconds
            self.fail_streak = 0
            self.last_notice_at = now
            return True
        return False
