"""Pairing token and rate limiting."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from typing import Callable, Optional


class TokenManager:
    def __init__(self, nbytes: int = 12) -> None:
        self.nbytes = nbytes
        self._lock = threading.Lock()
        self._token = self._new()

    def _new(self) -> str:
        return secrets.token_urlsafe(self.nbytes)

    @property
    def token(self) -> str:
        return self._token

    def rotate(self) -> str:
        with self._lock:
            self._token = self._new()
            return self._token

    def check(self, candidate: Optional[str]) -> bool:
        if not candidate or not isinstance(candidate, str):
            return False
        return hmac.compare_digest(candidate.encode(), self._token.encode())


class RateLimiter:
    """Allows at most one event per `min_interval` seconds."""

    def __init__(self, min_interval: float = 1.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.min_interval = min_interval
        self.clock = clock
        self._last: Optional[float] = None
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            now = self.clock()
            if self._last is not None and now - self._last < self.min_interval:
                return False
            self._last = now
            return True

    def retry_after(self) -> float:
        if self._last is None:
            return 0.0
        return max(0.0, self.min_interval - (self.clock() - self._last))


class FailureThrottle:
    """Counts bad-token attempts per client IP; blocks an IP after too many in a window."""

    def __init__(self, max_failures: int = 20, window: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.max_failures = max_failures
        self.window = window
        self.clock = clock
        self._hits: dict = {}
        self._lock = threading.Lock()

    def _prune(self, ip: str, now: float) -> list:
        hits = [t for t in self._hits.get(ip, []) if now - t < self.window]
        self._hits[ip] = hits
        return hits

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._prune(ip, self.clock())) >= self.max_failures

    def record(self, ip: str) -> None:
        with self._lock:
            now = self.clock()
            self._prune(ip, now).append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
