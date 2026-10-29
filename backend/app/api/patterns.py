"""Pembacaan pola candlestick (Hammer, Morning Star, Engulfing, dst.) per timeframe."""

from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.analysis.indicators import compute_indicators
from app.api.deps import SessionDep, resolve_instrument
from app.core.timeframes import Timeframe
from app.repositories import candles as candles_repo
from app.services.signal_engine import candles_to_frame
from app.strategies.common import TREND_TEXT, row_trend
from app.strategies.patterns import PatternRead, read_patterns, scan_patterns

router = APIRouter(tags=["patterns"])

PATTERN_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.H4)
FRAME_BARS = 300  # cukup untuk EMA200 + konteks pola


class PatternOut(BaseModel):
    name: str
    bias: int
    meaning: str
    strength: int
    strength_text: str
    note: str


class PatternMark(PatternOut):
    time: int


class TimeframePatterns(BaseModel):
    timeframe: Timeframe
    trend: str
    candle_time: int | None
    patterns: list[PatternOut]


class PatternConclusion(BaseModel):
    bias: Literal["BUY", "SELL", "MIXED", "NONE"]
    text: str


class PatternsResponse(BaseModel):
    symbol: str
    timeframes: list[TimeframePatterns]
    conclusion: PatternConclusion


def pattern_out(read: PatternRead) -> PatternOut:
    p = read.pattern
    return PatternOut(
        name=p.name,
        bias=p.bias,
        meaning=p.meaning,
        strength=read.strength,
        strength_text=read.strength_text,
        note=read.note,
    )


def pattern_marks(df: pd.DataFrame, bars: int) -> list[PatternMark]:
    """Pola berarah (bukan Spinning Top) di `bars` candle terakhir, untuk penanda grafik."""
    return [
        PatternMark(time=int(t.timestamp()), **pattern_out(r).model_dump())
        for t, r in scan_patterns(df, bars, row_trend)
        if r.pattern.bias
    ]


def conclude(frames: list[TimeframePatterns]) -> PatternConclusion:
    """Ringkasan: pola berarah (kekuatan sedang/kuat) dari timeframe besar diberi bobot lebih.
    Pola yang melawan tren H1 tidak dianggap arah, karena pembalikannya belum terkonfirmasi."""
    weight = {Timeframe.M15: 1.0, Timeframe.H1: 1.5, Timeframe.H4: 2.0}
    direction = {"naik": 1, "turun": -1}
    h1_trend = next((direction.get(f.trend, 0) for f in frames if f.timeframe == Timeframe.H1), 0)
    score, found = 0.0, []
    for f in frames:
        for p in f.patterns:
            if p.bias and p.strength >= 2:
                score += p.bias * p.strength * weight[f.timeframe]
                found.append(f"{p.name} {f.timeframe.value} ({p.strength_text})")
    if not found:
        return PatternConclusion(
            bias="NONE",
            text="Belum ada pola candlestick berarah yang cukup kuat di candle terakhir.",
        )
    listing = ", ".join(found)
    bias = 1 if score >= 2 else -1 if score <= -2 else 0
    if bias and h1_trend == -bias:
        word = "naik" if bias == 1 else "turun"
        return PatternConclusion(
            bias="MIXED",
            text=f"Pola {word} ({listing}) melawan tren H1 {TREND_TEXT[h1_trend]}: pembalikan "
            "belum terkonfirmasi, tunggu.",
        )
    if bias == 1:
        return PatternConclusion(bias="BUY", text=f"Pola condong NAIK: {listing}.")
    if bias == -1:
        return PatternConclusion(bias="SELL", text=f"Pola condong TURUN: {listing}.")
    return PatternConclusion(bias="MIXED", text=f"Pola campur/lemah: {listing}.")


@router.get("/patterns", response_model=PatternsResponse)
async def get_patterns(
    session: SessionDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
) -> PatternsResponse:
    """Pola candlestick pada candle TERTUTUP terakhir di M15, H1 dan H4, dengan kekuatannya
    (di area support/resistance? searah tren timeframe itu?)."""
    instrument = resolve_instrument(symbol)
    frames: list[TimeframePatterns] = []
    for tf in PATTERN_TIMEFRAMES:
        rows = await candles_repo.get_candles(session, instrument.symbol, tf, limit=FRAME_BARS)
        if len(rows) < 3:
            frames.append(TimeframePatterns(timeframe=tf, trend="-", candle_time=None, patterns=[]))
            continue
        df = compute_indicators(candles_to_frame(rows))
        trend = row_trend(df.iloc[-1])
        frames.append(
            TimeframePatterns(
                timeframe=tf,
                trend=TREND_TEXT[trend],
                candle_time=int(df.index[-1].timestamp()),
                patterns=[pattern_out(r) for r in read_patterns(df, trend)],
            )
        )
    return PatternsResponse(
        symbol=instrument.symbol, timeframes=frames, conclusion=conclude(frames)
    )
