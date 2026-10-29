from datetime import UTC, datetime, timedelta

from fakeredis import FakeAsyncRedis

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.providers.mock import MockProvider
from app.services.live_candle import get_live_candle

NOW = datetime(2026, 10, 28, 6, 7, 30, tzinfo=UTC)  # Rabu, candle M15 06:00 sedang berjalan


class CountingProvider(MockProvider):
    def __init__(self, now: datetime, remaining: int | None = None) -> None:
        super().__init__(clock=lambda: now)
        self.calls = 0
        self.remaining = remaining

    async def fetch_candles(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return await super().fetch_candles(*args, **kwargs)

    async def remaining_daily_credits(self) -> int | None:
        return self.remaining


async def test_returns_running_candle_and_shares_cache(eurusd: Instrument) -> None:
    redis = FakeAsyncRedis()
    provider = CountingProvider(NOW)
    kwargs = {"refresh_seconds": 20, "reserved_credits": 300}

    live, fetched_at, warning = await get_live_candle(
        provider, redis, eurusd, Timeframe.M15, NOW, **kwargs
    )
    assert live is not None and live.open_time == datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
    assert fetched_at is not None and warning is None

    # Viewer lain dalam interval refresh: pakai cache, tidak request ulang
    again, _, _ = await get_live_candle(
        provider, redis, eurusd, Timeframe.M15, NOW + timedelta(seconds=5), **kwargs
    )
    assert again == live
    assert provider.calls == 1


async def test_paused_when_daily_credits_reserved(eurusd: Instrument) -> None:
    provider = CountingProvider(NOW, remaining=250)
    live, _, warning = await get_live_candle(
        provider,
        FakeAsyncRedis(),
        eurusd,
        Timeframe.M15,
        NOW,
        refresh_seconds=20,
        reserved_credits=300,
    )
    assert live is None
    assert warning is not None and "Kuota" in warning
    assert provider.calls == 0


async def test_no_live_candle_when_market_closed(eurusd: Instrument) -> None:
    saturday = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    provider = CountingProvider(saturday)
    live, _, _ = await get_live_candle(
        provider,
        FakeAsyncRedis(),
        eurusd,
        Timeframe.M15,
        saturday,
        refresh_seconds=20,
        reserved_credits=0,
    )
    assert live is None and provider.calls == 0
