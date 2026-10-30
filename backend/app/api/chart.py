"""Analisis kondisi chart (tren, momentum, level) untuk kartu STRATEGI."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.analysis.indicators import compute_indicators
from app.api.deps import ProviderDep, SessionDep, resolve_instrument
from app.core.redis import get_redis
from app.core.timeframes import Timeframe
from app.repositories import candles as candles_repo
from app.repositories import instrument_settings as settings_repo
from app.services.candle_sync import refresh_if_stale
from app.services.chart_read import read_chart
from app.services.signal_engine import analysis_timeframes, candles_to_frame

router = APIRouter(tags=["analysis"])

FRAME_BARS = 300  # cukup untuk EMA200


class ChartPoint(BaseModel):
    tone: Literal["up", "down", "neutral", "warn"]
    text: str


class ChartReadOut(BaseModel):
    symbol: str
    timeframe: Timeframe
    lean: Literal["naik", "turun", "netral"]
    strength: Literal["kuat", "sedang", "lemah"]
    score: float
    headline: str
    points: list[ChartPoint]
    watch: str
    price: float | None
    support: float | None
    resistance: float | None


@router.get("/analysis/chart", response_model=ChartReadOut)
async def chart_analysis(
    session: SessionDep,
    provider: ProviderDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
    timeframe: Annotated[Timeframe, Query(description="Timeframe grafik yang dibuka")] = (
        Timeframe.M15
    ),
) -> ChartReadOut:
    """Ringkasan kondisi chart dalam bahasa sehari-hari. Bukan sinyal strategi teruji."""
    instrument = resolve_instrument(symbol)
    redis, now = get_redis(), datetime.now(UTC)
    frames = {}
    for tf in analysis_timeframes(timeframe):
        # Candle terbaru dulu: analisis ikut berubah setiap candle grafik tutup
        await refresh_if_stale(session, provider, redis, instrument, tf, now)
        rows = await candles_repo.get_candles(session, instrument.symbol, tf, limit=FRAME_BARS)
        if rows:
            frames[tf] = compute_indicators(candles_to_frame(rows))
    setting = (await settings_repo.get_all(session)).get(instrument.symbol)
    result = read_chart(frames, instrument, timeframe, setting.price_offset if setting else 0.0)
    return ChartReadOut(
        symbol=instrument.symbol,
        timeframe=result.timeframe,
        lean=result.lean,
        strength=result.strength,
        score=result.score,
        headline=result.headline,
        points=[ChartPoint(tone=p.tone, text=p.text) for p in result.points],
        watch=result.watch,
        price=result.price,
        support=result.support,
        resistance=result.resistance,
    )
