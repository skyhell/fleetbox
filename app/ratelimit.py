"""A small in-memory, fixed-window rate limiter for brute-force protection.

Keyed by an arbitrary string (e.g. client IP). Thread-safe because FastAPI runs
sync endpoints in a worker thread pool. Sufficient for a single-process
deployment; for multi-process/multi-host, back this with Redis instead.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]

    def is_allowed(self, key: str) -> bool:
        """Return True if another attempt is permitted (without recording it)."""
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            return len(self._hits[key]) < self.max_attempts

    def record_failure(self, key: str) -> None:
        """Count a failed attempt against the key."""
        now = time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._hits[key].append(now)

    def reset(self, key: str) -> None:
        """Clear attempts after a successful action."""
        with self._lock:
            self._hits.pop(key, None)

    def reset_all(self) -> None:
        """Clear all recorded attempts (used by tests)."""
        with self._lock:
            self._hits.clear()


def client_key(request) -> str:
    """Best-effort client identifier for rate limiting."""
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
