"""A small in-memory rate limiter.

Counts are kept per server process, which is fine for one uvicorn worker (the
recommended setup, see docs/DEPLOYMENT.md). If you later run several workers, each
keeps its own counts, so the real limit becomes limit x workers.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

from app.core.config import settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _sweep(self, now: float) -> None:
        for key in list(self._hits):
            self._recent(key, now)

    def check(self, key: str) -> None:
        """Raise 429 if this key has used up its allowance. Does not count a hit."""
        if not settings.RATE_LIMIT_ENABLED:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._recent(key, now)
            if hits is not None and len(hits) >= self.limit:
                retry = int(hits[0] + self.window - now) + 1
                minutes = max(1, -(-retry // 60))
                raise HTTPException(
                    429,
                    f"Too many attempts. Please try again in {minutes} minute(s).",
                    headers={"Retry-After": str(retry)},
                )

    def hit(self, key: str) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 10_000:  # keep memory bounded
                self._sweep(now)
            self._recent(key, now)
            self._hits[key].append(now)

    def check_and_hit(self, key: str) -> None:
        self.check(key)
        self.hit(key)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


# Wrong passwords: 5 per sign-in name and address per 15 minutes. Only failures count,
# so many people behind the church wifi can still sign in normally.
login_failures = SlidingWindowLimiter(limit=5, window_seconds=15 * 60)
# The same sign-in name from anywhere: 20 wrong passwords per hour. This still holds when an
# attacker changes (or fakes) their address on every try.
login_account_failures = SlidingWindowLimiter(limit=20, window_seconds=60 * 60)
password_change_failures = SlidingWindowLimiter(limit=5, window_seconds=15 * 60)

# Wrong check-in codes: 10 per member every 5 minutes (a code has only a million
# possibilities, so guessing has to be slow).
code_failures = SlidingWindowLimiter(limit=10, window_seconds=5 * 60)

# Failed fingerprint/face confirmations at check-in: 10 per member every 5 minutes.
passkey_failures = SlidingWindowLimiter(limit=10, window_seconds=5 * 60)

# Generous because a whole congregation may share one address.
signup_limiter = SlidingWindowLimiter(limit=30, window_seconds=60 * 60)

forgot_ip_limiter = SlidingWindowLimiter(limit=10, window_seconds=60 * 60)
forgot_email_limiter = SlidingWindowLimiter(limit=3, window_seconds=60 * 60)
reset_limiter = SlidingWindowLimiter(limit=20, window_seconds=60 * 60)
