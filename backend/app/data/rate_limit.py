"""Rate limiter berbasis Redis, dipakai bersama oleh API dan worker."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.data.errors import RateLimitError

logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """Window tetap per menit + kuota harian (UTC), dihitung dalam 'credit'."""

    def __init__(
        self,
        redis: Redis,
        name: str,
        per_minute: int,
        per_day: int,
        *,
        per_hour: int | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._redis = redis
        self._name = name
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._per_day = per_day
        self._clock = clock
        self._sleep = sleep

    @property
    def per_day(self) -> int:
        return self._per_day

    def _day_key(self, now: float) -> str:
        return f"ratelimit:{self._name}:day:{datetime.fromtimestamp(now, UTC):%Y%m%d}"

    async def used_today(self) -> int:
        return int(await self._redis.get(self._day_key(self._clock())) or 0)

    async def mark_exhausted(self) -> None:
        """Provider melaporkan kuota harian habis (mis. key yang sama dipakai di tempat lain):
        samakan penghitung agar request berikutnya ditolak lokal sampai hari berganti (UTC)."""
        day_key = self._day_key(self._clock())
        await self._redis.set(day_key, self._per_day, ex=2 * 86400)

    async def acquire(self, cost: int = 1, max_wait: float = 130.0) -> None:
        deadline = self._clock() + max_wait
        while True:
            now = self._clock()
            day_key = self._day_key(now)
            if int(await self._redis.get(day_key) or 0) + cost > self._per_day:
                raise RateLimitError(
                    f"Kuota harian {self._name} ({self._per_day} request) sudah habis"
                )

            if self._per_hour is not None:
                hour_key = f"ratelimit:{self._name}:hour:{int(now // 3600)}"
                if int(await self._redis.get(hour_key) or 0) + cost > self._per_hour:
                    raise RateLimitError(
                        f"Batas per jam {self._name} ({self._per_hour} request) tercapai"
                    )

            minute_key = f"ratelimit:{self._name}:min:{int(now // 60)}"
            used = await self._redis.incrby(minute_key, cost)
            await self._redis.expire(minute_key, 120)
            if used <= self._per_minute:
                await self._redis.incrby(day_key, cost)
                await self._redis.expire(day_key, 2 * 86400)
                if self._per_hour is not None:
                    await self._redis.incrby(hour_key, cost)
                    await self._redis.expire(hour_key, 7200)
                return

            await self._redis.decrby(minute_key, cost)
            wait = 60 - (now % 60) + 0.5
            if now + wait > deadline:
                raise RateLimitError(f"Batas per menit {self._name} tercapai")
            logger.info("Batas %s/menit tercapai, menunggu %.0f detik", self._per_minute, wait)
            await self._sleep(wait)
