from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

from app.analysis.filters import FilterConfig, news_block, volatility_block, weekend_close_block
from app.analysis.narrator import Narrator
from app.analysis.news import NewsEvent
from app.analysis.risk import pip_value_per_lot_usd, price_to_pips, suggest_lot
from app.core.instruments import Instrument


def test_lot_size_gold(xauusd: Instrument) -> None:
    # Risiko $10, SL 15 pip × $10/pip/lot → 0.0667 → dibulatkan ke bawah 0.06
    lot = suggest_lot(xauusd, capital=1000, risk_percent=1, entry=4000.0, stop_loss=3998.5)
    assert lot == 0.06


def test_lot_size_eurusd(eurusd: Instrument) -> None:
    lot = suggest_lot(eurusd, capital=10_000, risk_percent=1, entry=1.16, stop_loss=1.158)
    assert lot == 0.5


def test_lot_size_usdjpy(eurusd: Instrument) -> None:
    usdjpy = eurusd.model_copy(
        update={"symbol": "USDJPY", "pip_size": 0.01, "digits": 3, "quote_currency": "JPY"}
    )
    assert pip_value_per_lot_usd(usdjpy, 150.0) == 1000 / 150
    assert suggest_lot(usdjpy, capital=10_000, risk_percent=1, entry=150.0, stop_loss=149.8) == 0.75


def test_lot_too_small_returns_zero(xauusd: Instrument) -> None:
    assert suggest_lot(xauusd, capital=50, risk_percent=1, entry=4000.0, stop_loss=3990.0) == 0.0


def test_price_to_pips(xauusd: Instrument) -> None:
    assert price_to_pips(-1.5, xauusd) == 15.0


def _atr_frame(last_atr: float, last_range: float = 1.0) -> pd.DataFrame:
    atr = np.full(120, 1.0)
    atr[-1] = last_atr
    df = pd.DataFrame({"atr": atr, "high": 101.0, "low": 100.0})
    df.loc[df.index[-1], "high"] = 100 + last_range
    return df


def test_volatility_filter() -> None:
    cfg = FilterConfig()
    assert volatility_block(_atr_frame(1.0), cfg) is None
    assert "ekstrem" in (volatility_block(_atr_frame(3.0), cfg) or "")
    assert "sepi" in (volatility_block(_atr_frame(0.2, 0.2), cfg) or "")
    assert "sangat besar" in (volatility_block(_atr_frame(1.2, 4.0), cfg) or "")


def test_weekend_close_filter(eurusd: Instrument) -> None:
    cfg = FilterConfig()
    friday_late = datetime(2026, 10, 30, 20, 30, tzinfo=UTC)  # 16:30 New York
    assert weekend_close_block(eurusd, friday_late, cfg) is not None
    assert weekend_close_block(eurusd, friday_late - timedelta(hours=3), cfg) is None


class FakeCalendar:
    def __init__(self, events: list[NewsEvent]) -> None:
        self._events = events

    async def events(self, currencies: set[str], start: datetime, end: datetime) -> list[NewsEvent]:
        return [e for e in self._events if e.currency in currencies and start <= e.time <= end]


async def test_news_filter(xauusd: Instrument, eurusd: Instrument) -> None:
    now = datetime(2026, 11, 6, 13, 15, tzinfo=UTC)
    nfp = NewsEvent(datetime(2026, 11, 6, 13, 30, tzinfo=UTC), "USD", "high", "Non-Farm Payrolls")
    eur_low = NewsEvent(now, "EUR", "low", "Minor")
    cal = FakeCalendar([nfp, eur_low])
    cfg = FilterConfig()

    assert "Non-Farm Payrolls" in (await news_block(cal, xauusd, now, cfg) or "")
    assert await news_block(cal, xauusd, now - timedelta(hours=2), cfg) is None
    assert await news_block(FakeCalendar([eur_low]), eurusd, now, cfg) is None  # dampak rendah


async def test_narrator_without_key_uses_rules() -> None:
    text = await Narrator("", "m").describe({}, ["Tren naik.", "RSI keluar."])
    assert text == "Tren naik. RSI keluar."


async def test_narrator_uses_groq_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": ' "Harga  sedang naik." '}}]}
        )

    narrator = Narrator("k", "m", transport=httpx.MockTransport(handler))
    assert await narrator.describe({"aksi": "BUY"}, ["x"]) == "Harga sedang naik."


async def test_narrator_falls_back_on_error() -> None:
    narrator = Narrator("k", "m", transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    assert await narrator.describe({}, ["Alasan aturan."]) == "Alasan aturan."
