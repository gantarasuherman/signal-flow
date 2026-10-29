from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.errors import ProviderConfigError, RateLimitError
from app.data.providers.twelvedata import BASE_URL, TwelveDataProvider


async def _no_sleep(_: float) -> None:
    return None


def make_provider(handler: Any, api_key: str = "test-key") -> TwelveDataProvider:
    client = httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return TwelveDataProvider(api_key, client=client, sleep=_no_sleep)


async def test_parses_candles_sorted_and_uses_utc(xauusd: Instrument) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {
                        "datetime": "2026-10-29 01:15:00",
                        "open": "4001.5",
                        "high": "4003",
                        "low": "4000.1",
                        "close": "4002.2",
                    },
                    {
                        "datetime": "2026-10-29 01:00:00",
                        "open": "3999",
                        "high": "4002",
                        "low": "3998.5",
                        "close": "4001.5",
                    },
                ],
            },
        )

    candles = await make_provider(handler).fetch_candles(xauusd, Timeframe.M15, limit=2)

    assert seen["symbol"] == "XAU/USD"
    assert seen["interval"] == "15min"
    assert seen["timezone"] == "UTC"
    assert [c.open_time for c in candles] == [
        datetime(2026, 10, 29, 1, 0, tzinfo=UTC),
        datetime(2026, 10, 29, 1, 15, tzinfo=UTC),
    ]
    assert candles[1].close == 4002.2
    assert candles[1].volume is None


async def test_invalid_rows_skipped(xauusd: Instrument) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "values": [
                    {
                        "datetime": "2026-10-29 01:00:00",
                        "open": "x",
                        "high": "1",
                        "low": "1",
                        "close": "1",
                    },
                    {
                        "datetime": "2026-10-29 01:15:00",
                        "open": "5",
                        "high": "4",
                        "low": "6",
                        "close": "5",
                    },
                ]
            },
        )

    assert await make_provider(handler).fetch_candles(xauusd, Timeframe.M15) == []


async def test_no_data_returns_empty(xauusd: Instrument) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "error",
                "code": 400,
                "message": "No data is available on the specified dates. "
                "Try setting different start/end dates.",
            },
        )

    assert await make_provider(handler).fetch_candles(xauusd, Timeframe.M15) == []


async def test_rate_limit_retried_then_raises(xauusd: Instrument) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"status": "error", "code": 429, "message": "limit"})

    with pytest.raises(RateLimitError):
        await make_provider(handler).fetch_candles(xauusd, Timeframe.M15)
    assert calls == 3


async def test_server_error_then_success(xauusd: Instrument) -> None:
    responses = iter([httpx.Response(503), httpx.Response(200, json={"price": "4010.25"})])
    quote = await make_provider(lambda _: next(responses)).fetch_price(xauusd)
    assert quote.price == 4010.25


async def test_missing_api_key(xauusd: Instrument) -> None:
    provider = make_provider(lambda _: httpx.Response(200, json={}), api_key="")
    with pytest.raises(ProviderConfigError, match="TWELVEDATA_API_KEY"):
        await provider.fetch_price(xauusd)


async def test_invalid_key_is_config_error(xauusd: Instrument) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "error", "code": 401, "message": "invalid api key"}
        )

    with pytest.raises(ProviderConfigError):
        await make_provider(handler).fetch_price(xauusd)
