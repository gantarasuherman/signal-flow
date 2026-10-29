from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CandleDTO:
    """Candle OHLC dari provider. `open_time` selalu UTC."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True, slots=True)
class PriceQuote:
    price: float
    timestamp: datetime
