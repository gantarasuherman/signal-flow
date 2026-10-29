import pytest
from fakeredis import FakeAsyncRedis

from app.data.errors import RateLimitError
from app.data.rate_limit import RedisRateLimiter


class FakeClock:
    def __init__(self, start: float) -> None:
        self.now = start
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_waits_for_next_minute_when_minute_quota_used() -> None:
    clock = FakeClock(start=1_800_000_000.0 + 10)  # detik ke-10 dalam satu menit
    limiter = RedisRateLimiter(
        FakeAsyncRedis(), "td", per_minute=2, per_day=100, clock=clock.time, sleep=clock.sleep
    )
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()  # harus menunggu menit berikutnya

    assert len(clock.slept) == 1
    assert clock.slept[0] == pytest.approx(50.5)
    assert await limiter.used_today() == 3


async def test_daily_quota_exhausted() -> None:
    clock = FakeClock(start=1_800_000_000.0)
    limiter = RedisRateLimiter(
        FakeAsyncRedis(), "td", per_minute=10, per_day=2, clock=clock.time, sleep=clock.sleep
    )
    await limiter.acquire()
    await limiter.acquire()
    with pytest.raises(RateLimitError, match="harian"):
        await limiter.acquire()


async def test_max_wait_exceeded() -> None:
    clock = FakeClock(start=1_800_000_000.0)
    limiter = RedisRateLimiter(
        FakeAsyncRedis(), "td", per_minute=1, per_day=10, clock=clock.time, sleep=clock.sleep
    )
    await limiter.acquire()
    with pytest.raises(RateLimitError, match="per menit"):
        await limiter.acquire(max_wait=5)
