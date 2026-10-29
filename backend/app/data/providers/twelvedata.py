"""Adapter Twelve Data (https://twelvedata.com/docs)."""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.errors import (
    NoDataError,
    ProviderConfigError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.data.providers.base import MAX_BATCH, DataProvider
from app.data.rate_limit import RedisRateLimiter
from app.data.schemas import CandleDTO, PriceQuote

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"
INTERVALS = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
}
DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def _format_dt(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(value: str) -> datetime:
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ProviderError(f"Format waktu tidak dikenal dari Twelve Data: {value!r}")


def parse_candles(values: list[dict[str, Any]]) -> list[CandleDTO]:
    candles: list[CandleDTO] = []
    for row in values:
        try:
            o, h, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            logger.warning("Baris candle tidak valid dilewati: %s", row)
            continue
        if not all(map(math.isfinite, (o, h, lo, c))) or h < lo:
            logger.warning("Candle tidak wajar dilewati: %s", row)
            continue
        volume = row.get("volume")
        candles.append(
            CandleDTO(
                open_time=_parse_dt(row["datetime"]),
                open=o,
                high=max(h, o, c),
                low=min(lo, o, c),
                close=c,
                volume=float(volume) if volume not in (None, "") else None,
            )
        )
    candles.sort(key=lambda candle: candle.open_time)
    return candles


class TwelveDataProvider(DataProvider):
    name = "twelvedata"

    def __init__(
        self,
        api_key: str,
        limiter: RedisRateLimiter | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._limiter = limiter
        self._client = client or httpx.AsyncClient(base_url=BASE_URL, timeout=20.0)
        self._max_retries = max_retries
        self._sleep = sleep

    async def aclose(self) -> None:
        await self._client.aclose()

    async def remaining_daily_credits(self) -> int | None:
        if self._limiter is None:
            return None
        return self._limiter.per_day - await self._limiter.used_today()

    async def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderConfigError("TWELVEDATA_API_KEY belum diisi di .env")

        for attempt in range(1, self._max_retries + 1):
            if self._limiter:
                await self._limiter.acquire()
            try:
                resp = await self._client.get(path, params={**params, "apikey": self._api_key})
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise ProviderUnavailableError(f"Twelve Data tidak terjangkau: {exc}") from exc
                logger.warning("Koneksi Twelve Data gagal (%s), retry %d", exc, attempt)
                await self._sleep(2**attempt)
                continue

            if resp.status_code >= 500:
                if attempt == self._max_retries:
                    raise ProviderUnavailableError(f"Twelve Data HTTP {resp.status_code}")
                await self._sleep(2**attempt)
                continue

            try:
                data = resp.json()
            except ValueError as exc:
                raise ProviderError("Respons Twelve Data bukan JSON") from exc

            # Twelve Data mengembalikan error dalam body: {"status": "error", "code": 429, ...}
            if isinstance(data, dict) and data.get("status") == "error":
                code = int(data.get("code", resp.status_code))
            elif resp.status_code >= 400:
                code = resp.status_code
            else:
                return data

            message = str(data.get("message", "")) if isinstance(data, dict) else resp.text
            if code == 429:
                if "for the day" in message.lower():
                    # Kuota harian habis: menunggu 60 detik tidak membantu, hanya membuang kredit
                    if self._limiter:
                        await self._limiter.mark_exhausted()
                    raise RateLimitError(f"Kuota harian Twelve Data habis. {message}")
                if attempt == self._max_retries:
                    raise RateLimitError(message or "Rate limit Twelve Data")
                logger.warning("Rate limit Twelve Data, menunggu 60 detik")
                await self._sleep(60)
                continue
            if code == 400 and "no data" in message.lower():
                raise NoDataError(message)
            if code in (401, 403, 404):
                raise ProviderConfigError(f"Twelve Data {code}: {message}")
            raise ProviderError(f"Twelve Data {code}: {message}")

        raise ProviderUnavailableError("Twelve Data gagal setelah retry")

    async def fetch_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[CandleDTO]:
        params: dict[str, Any] = {
            "symbol": instrument.provider_symbol,
            "interval": INTERVALS[timeframe],
            "outputsize": min(limit, MAX_BATCH),
            "timezone": "UTC",
            "order": "ASC",
        }
        if start:
            params["start_date"] = _format_dt(start)
        if end:
            params["end_date"] = _format_dt(end)

        try:
            data = await self._request("/time_series", params)
        except NoDataError:
            return []
        return parse_candles(data.get("values") or [])

    async def fetch_price(self, instrument: Instrument) -> PriceQuote:
        data = await self._request("/price", {"symbol": instrument.provider_symbol})
        try:
            price = float(data["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"Harga tidak valid dari Twelve Data: {data}") from exc
        return PriceQuote(price=price, timestamp=datetime.now(UTC))
