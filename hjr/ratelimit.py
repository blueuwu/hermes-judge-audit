"""Thread-safe token bucket, one per endpoint."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        rpm: int,
        *,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self.rate = rpm / 60.0  # tokens per second
        self.capacity = float(burst if burst is not None else max(1, rpm // 10))
        self._tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def acquire(self) -> float:
        """Block until a request may be sent. Returns the seconds spent waiting."""
        waited = 0.0
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return waited
                delay = (1 - self._tokens) / self.rate
            self._sleep(delay)
            waited += delay


class Limiters:
    """Lazily created bucket per limiter key (an endpoint, or a model with its own cap)."""

    def __init__(self, rpm_by_key: dict[str, int]):
        self._rpm = rpm_by_key
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> TokenBucket:
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(self._rpm[key])
            return self._buckets[key]
