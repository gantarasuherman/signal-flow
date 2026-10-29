"""Filter yang memblokir sinyal entry baru pada kondisi pasar berisiko."""

from datetime import datetime, timedelta

import pandas as pd
from pydantic import BaseModel, Field

from app.analysis.news import NewsCalendar
from app.core.instruments import Instrument
from app.core.market_hours import is_market_open


class FilterConfig(BaseModel):
    max_atr_ratio: float = Field(default=2.5, gt=1, description="ATR / median ATR 100 candle")
    min_atr_ratio: float = Field(default=0.3, ge=0, lt=1)
    max_candle_atr: float = Field(default=3.0, gt=1, description="Range candle terakhir / ATR")
    news_before_minutes: int = Field(default=30, ge=0)
    news_after_minutes: int = Field(default=30, ge=0)
    news_min_impact: str = Field(default="high", pattern="^(low|medium|high)$")
    weekend_close_buffer_minutes: int = Field(default=45, ge=0)


IMPACT_RANK = {"low": 0, "medium": 1, "high": 2}


def instrument_currencies(instrument: Instrument) -> set[str]:
    return {instrument.symbol[:3], instrument.quote_currency}


def volatility_block(m15: pd.DataFrame, cfg: FilterConfig) -> str | None:
    last = m15.iloc[-1]
    atr = float(last["atr"])
    median_atr = float(m15["atr"].tail(100).median())
    if median_atr > 0:
        ratio = atr / median_atr
        if ratio > cfg.max_atr_ratio:
            return f"Volatilitas ekstrem: ATR {ratio:.1f}× dari normal."
        if ratio < cfg.min_atr_ratio:
            return f"Pasar terlalu sepi: ATR hanya {ratio:.1f}× dari normal."
    candle_range = float(last["high"] - last["low"])
    if atr > 0 and candle_range > cfg.max_candle_atr * atr:
        return f"Candle terakhir sangat besar ({candle_range / atr:.1f}× ATR), tunggu harga tenang."
    return None


def weekend_close_block(instrument: Instrument, now: datetime, cfg: FilterConfig) -> str | None:
    later = now + timedelta(minutes=cfg.weekend_close_buffer_minutes)
    if is_market_open(instrument.asset_class, now) and not is_market_open(
        instrument.asset_class, later
    ):
        return "Pasar segera tutup, hindari membuka posisi baru."
    return None


async def news_block(
    calendar: NewsCalendar, instrument: Instrument, now: datetime, cfg: FilterConfig
) -> str | None:
    events = await calendar.events(
        instrument_currencies(instrument),
        now - timedelta(minutes=cfg.news_after_minutes),
        now + timedelta(minutes=cfg.news_before_minutes),
    )
    important = [e for e in events if IMPACT_RANK[e.impact] >= IMPACT_RANK[cfg.news_min_impact]]
    if not important:
        return None
    event = min(important, key=lambda e: abs((e.time - now).total_seconds()))
    return f"Dekat rilis berita {event.currency}: {event.title} ({event.time:%H:%M} UTC)."


async def run_filters(
    m15: pd.DataFrame,
    instrument: Instrument,
    now: datetime,
    cfg: FilterConfig,
    calendar: NewsCalendar,
) -> list[str]:
    reasons = [
        volatility_block(m15, cfg),
        weekend_close_block(instrument, now, cfg),
        await news_block(calendar, instrument, now, cfg),
    ]
    return [r for r in reasons if r]
