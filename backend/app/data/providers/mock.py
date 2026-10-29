"""Provider sintetis untuk pengembangan & pengujian tanpa API key.

Harga dibentuk dari gabungan gelombang sinus sehingga deterministik: candle yang sama
selalu menghasilkan nilai yang sama, dan timeframe berbeda saling konsisten.
"""

import math
import random
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.instruments import Instrument
from app.core.market_hours import candle_has_trading
from app.core.timeframes import Timeframe, floor_to_timeframe
from app.data.providers.base import MAX_BATCH, DataProvider
from app.data.schemas import CandleDTO, PriceQuote

BASE_PRICES = {"XAUUSD": 4000.0, "EURUSD": 1.16, "GBPUSD": 1.33, "USDJPY": 152.0}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MockProvider(DataProvider):
    name = "mock"

    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock

    @staticmethod
    def _mid(symbol: str, ts: datetime) -> float:
        base = BASE_PRICES.get(symbol, 100.0)
        x = ts.timestamp() / 60
        phase = sum(map(ord, symbol)) % 97
        wave = (
            0.03 * math.sin(x / 20000 + phase)
            + 0.008 * math.sin(x / 2100 + 2 * phase)
            + 0.0025 * math.sin(x / 240 + phase)
            + 0.0008 * math.sin(x / 31)
        )
        return base * (1 + wave)

    def _candle(self, instrument: Instrument, open_time: datetime, tf: Timeframe) -> CandleDTO:
        steps = min(tf.minutes, 16)
        points = [
            self._mid(instrument.symbol, open_time + tf.delta * i / steps) for i in range(steps + 1)
        ]
        rng = random.Random(f"{instrument.symbol}|{tf.value}|{int(open_time.timestamp())}")
        wick = (max(points) - min(points) + points[0] * 0.0001) * 0.3
        return CandleDTO(
            open_time=open_time,
            open=instrument.round_price(points[0]),
            high=instrument.round_price(max(points) + rng.random() * wick),
            low=instrument.round_price(min(points) - rng.random() * wick),
            close=instrument.round_price(points[-1]),
        )

    async def fetch_candles(
        self,
        instrument: Instrument,
        timeframe: Timeframe,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[CandleDTO]:
        now = self._clock()
        limit = min(limit, MAX_BATCH)
        # Seperti provider asli: candle yang sedang berjalan ikut dikembalikan
        t = floor_to_timeframe(min(end, now) if end else now, timeframe)
        lower = floor_to_timeframe(start, timeframe) if start else None
        guard = t - timeframe.delta * (limit * 3 + 3000)

        times: list[datetime] = []
        while len(times) < limit and t > guard and (lower is None or t >= lower):
            if candle_has_trading(instrument.asset_class, t, timeframe):
                times.append(t)
            t -= timeframe.delta
        return [self._candle(instrument, ot, timeframe) for ot in reversed(times)]

    async def fetch_price(self, instrument: Instrument) -> PriceQuote:
        now = self._clock()
        return PriceQuote(
            price=instrument.round_price(self._mid(instrument.symbol, now)), timestamp=now
        )
