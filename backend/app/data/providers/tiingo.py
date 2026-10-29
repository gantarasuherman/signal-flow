"""Adapter Tiingo FX (https://www.tiingo.com/documentation/forex).

Ticker = simbol instrumen huruf kecil (XAUUSD → xauusd). Parameter tanggal Tiingo hanya
memakai bagian tanggal, jadi rentang jam yang tepat disaring di sini. Harga = mid."""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.errors import (
    ProviderConfigError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.data.providers.base import MAX_BATCH, DataProvider
from app.data.rate_limit import RedisRateLimiter
from app.data.schemas import CandleDTO, PriceQuote

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tiingo.com"
RESAMPLE = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.H1: "1hour",
    Timeframe.H4: "4hour",
}


def ticker(instrument: Instrument) -> str:
    return instrument.symbol.lower()


def parse_candles(rows: list[dict[str, Any]]) -> list[CandleDTO]:
    candles: list[CandleDTO] = []
    for row in rows:
        try:
            o, h, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            open_time = datetime.fromisoformat(row["date"].replace("Z", "+00:00")).astimezone(UTC)
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.warning("Baris candle Tiingo tidak valid dilewati: %s", row)
            continue
        if not all(map(math.isfinite, (o, h, lo, c))) or h < lo:
            logger.warning("Candle Tiingo tidak wajar dilewati: %s", row)
            continue
        candles.append(
            CandleDTO(open_time=open_time, open=o, high=max(h, o, c), low=min(lo, o, c), close=c)
        )
    candles.sort(key=lambda candle: candle.open_time)
    return candles


class TiingoProvider(DataProvider):
    name = "tiingo"

    def __init__(
        self,
        api_key: str,
        limiter: RedisRateLimiter | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._limiter = limiter
        self._client = client or httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def remaining_daily_credits(self) -> int | None:
        if self._limiter is None:
            return None
        return self._limiter.per_day - await self._limiter.used_today()

    async def _request(self, path: str, params: dict[str, Any]) -> Any:
        if not self._api_key:
            raise ProviderConfigError("TIINGO_API_KEY belum diisi di .env")
        if self._limiter:
            await self._limiter.acquire()
        try:
            resp = await self._client.get(
                path, params=params, headers={"Authorization": f"Token {self._api_key}"}
            )
        except httpx.TransportError as exc:
            raise ProviderUnavailableError(f"Tiingo tidak terjangkau: {exc}") from exc
        if resp.status_code == 200:
            return resp.json()
        try:
            detail = str(resp.json().get("detail", resp.text))
        except ValueError:
            detail = resp.text
        if resp.status_code == 429:
            raise RateLimitError(f"Batas request Tiingo tercapai. {detail}")
        if resp.status_code in (401, 403):
            raise ProviderConfigError(f"Tiingo {resp.status_code}: {detail}")
        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"Tiingo HTTP {resp.status_code}")
        raise ProviderError(f"Tiingo {resp.status_code}: {detail}")

    async def fetch_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[CandleDTO]:
        limit = min(limit, MAX_BATCH)
        until = end or datetime.now(UTC)
        # Tanpa `start`: ambil cukup hari untuk `limit` candle (+ akhir pekan)
        since = start or until - timeframe.delta * limit * 1.6 - timedelta(days=4)
        params = {
            "resampleFreq": RESAMPLE[timeframe],
            "startDate": since.astimezone(UTC).date().isoformat(),
            "endDate": (until.astimezone(UTC).date() + timedelta(days=1)).isoformat(),
        }
        data = await self._request(f"/tiingo/fx/{ticker(instrument)}/prices", params)
        if not isinstance(data, list):
            raise ProviderError(f"Respons Tiingo tidak terduga: {str(data)[:200]}")
        candles = [
            c
            for c in parse_candles(data)
            if (start is None or c.open_time >= start) and (end is None or c.open_time <= end)
        ]
        return candles[-limit:]

    async def fetch_price(self, instrument: Instrument) -> PriceQuote:
        data = await self._request("/tiingo/fx/top", {"tickers": ticker(instrument)})
        try:
            quote = data[0]
            price = float(quote["midPrice"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"Harga tidak valid dari Tiingo: {data}") from exc
        return PriceQuote(price=price, timestamp=datetime.now(UTC))
