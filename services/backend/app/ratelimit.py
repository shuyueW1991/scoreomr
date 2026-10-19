"""A tiny in-process sliding-window limiter for auth/upload endpoints.

The deployment runs one API process; this protects against casual brute force
and upload floods without adding Redis.  Persistent fairness (the free daily
quota) lives in SQLite instead.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> tuple[bool, int]:
        """Record an attempt. Returns (allowed, retry_after_seconds)."""
        if self.limit <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.window
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                retry = max(1, int(self.window - (now - q[0])) + 1)
                return False, retry
            q.append(now)
            if len(self._hits) > 20_000:
                for stale_key, stale_q in list(self._hits.items())[:1000]:
                    if not stale_q or stale_q[-1] < cutoff:
                        self._hits.pop(stale_key, None)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
