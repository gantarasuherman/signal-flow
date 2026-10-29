from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.errors import ProviderConfigError, RateLimitError
from app.data.providers import SwitchableProvider
from app.data.providers.mock import MockProvider
from app.data.providers.tiingo import BASE_URL, TiingoProvider
from app.data.rate_limit import RedisRateLimiter


def make_provider(handler: Any, api_key: str = "k") -> TiingoProvider:
    client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return TiingoProvider(api_key, client=client)


def row(date: str, close: float) -> dict[str, Any]:
    return {
        "date": date,
        "ticker": "xauusd",
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
    }


async def test_candles_parsed_filtered_and_dated(xauusd: Instrument) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["params"] = request.url.path, dict(request.url.params)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json=[
                row("2026-10-29T13:45:00.000Z", 4020.0),
                row("2026-10-29T14:00:00.000Z", 4021.0),
                row("2026-10-29T14:15:00.000Z", 4022.0),
            ],
        )

    start = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
    candles = await make_provider(handler).fetch_candles(xauusd, Timeframe.M15, start=start)
    assert seen["path"] == "/tiingo/fx/xauusd/prices"
    assert seen["params"]["resampleFreq"] == "15min"
    assert seen["params"]["startDate"] == "2026-10-29"  # Tiingo hanya memakai tanggal
    assert seen["auth"] == "Token k"
    assert [c.close for c in candles] == [4021.0, 4022.0]  # 13:45 disaring
    assert candles[0].open_time == start


async def test_limit_keeps_latest(xauusd: Instrument) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[row(f"2026-10-29T1{i}:00:00.000Z", 4000 + i) for i in range(5)]
        )

    candles = await make_provider(handler).fetch_candles(xauusd, Timeframe.H1, limit=2)
    assert [c.close for c in candles] == [4003, 4004]


async def test_price_uses_mid(xauusd: Instrument) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"ticker": "xauusd", "bidPrice": 4021.45, "askPrice": 4021.55, "midPrice": 4021.5}
            ],
        )

    assert (await make_provider(handler).fetch_price(xauusd)).price == 4021.5


async def test_errors(xauusd: Instrument) -> None:
    def limited(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "Rate limit"})

    def forbidden(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid token"})

    with pytest.raises(RateLimitError):
        await make_provider(limited).fetch_candles(xauusd, Timeframe.M15)
    with pytest.raises(ProviderConfigError):
        await make_provider(forbidden).fetch_candles(xauusd, Timeframe.M15)
    with pytest.raises(ProviderConfigError):
        await make_provider(limited, api_key="").fetch_candles(xauusd, Timeframe.M15)


async def test_hourly_limit() -> None:
    limiter = RedisRateLimiter(FakeAsyncRedis(), "t", per_minute=10, per_day=100, per_hour=2)
    await limiter.acquire()
    await limiter.acquire()
    with pytest.raises(RateLimitError, match="per jam"):
        await limiter.acquire()


class Named(MockProvider):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name


async def test_switchable_follows_saved_choice_with_fallback() -> None:
    choice: dict[str, str | None] = {"value": None}
    now = {"t": 0.0}

    async def load() -> str | None:
        return choice["value"]

    sw = SwitchableProvider(
        {"twelvedata": Named("twelvedata"), "tiingo": Named("tiingo")},
        default="twelvedata",
        load_choice=load,
        clock=lambda: now["t"],
    )
    assert await sw.active_name() == "twelvedata"
    choice["value"] = "tiingo"
    assert await sw.active_name() == "twelvedata"  # masih di-cache
    now["t"] = 10
    assert await sw.active_name() == "tiingo" and sw.name == "tiingo"
    assert (await sw.current()).name == "tiingo"
    choice["value"] = "unknown"
    sw.invalidate()
    assert await sw.active_name() == "twelvedata"  # pilihan tak dikenal → bawaan
