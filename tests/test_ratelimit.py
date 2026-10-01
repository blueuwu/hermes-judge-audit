from __future__ import annotations

import pytest

from hjr.ratelimit import Limiters, TokenBucket


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_burst_then_steady_rate():
    clock = FakeClock()
    bucket = TokenBucket(60, burst=3, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        assert bucket.acquire() == 0.0
    waits = [bucket.acquire() for _ in range(5)]
    assert all(w == pytest.approx(1.0) for w in waits)
    assert clock.t == pytest.approx(5.0)


def test_ten_rpm_spaces_requests_six_seconds_apart():
    clock = FakeClock()
    bucket = TokenBucket(10, clock=clock, sleep=clock.sleep)
    bucket.acquire()
    assert bucket.acquire() == pytest.approx(6.0)


def test_limiters_share_a_bucket_per_endpoint():
    limiters = Limiters({"a": 60, "b": 10})
    assert limiters.get("a") is limiters.get("a")
    assert limiters.get("a") is not limiters.get("b")


def test_rejects_non_positive_rpm():
    with pytest.raises(ValueError):
        TokenBucket(0)
