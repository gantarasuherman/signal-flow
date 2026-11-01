"""Bukti historis untuk AI: seberapa sering pola candle, analisis chart, dan AI sendiri benar
di instrumen & timeframe ini. Dihitung kode dari data tersimpan lalu dikirim ke prompt AI,
agar AI menimbang setup dengan rekam jejak nyata, bukan teori pola saja."""

from datetime import UTC, datetime, timedelta

import pandas as pd
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.db.models import Signal
from app.repositories import signals as signals_repo
from app.services.chart_read import read_chart
from app.services.pattern_stats import MIN_EDGE, MIN_SAMPLES, get_pattern_stats, wilson_lower
from app.strategies.patterns import detect_patterns

TRACK_RECORD_DAYS = 30


def pattern_notes(df: pd.DataFrame, stats: dict, tf: Timeframe) -> list[str]:
    notes = []
    for p in detect_patterns(df):
        if not p.bias:
            continue
        side = "BUY" if p.bias > 0 else "SELL"
        stat = stats.get(p.name)
        if stat is None or stat.samples < MIN_SAMPLES:
            notes.append(f"Pattern {p.name} ({side} bias) on last {tf} candle: too few past cases.")
            continue
        verdict = (
            "RELIABLE"
            if stat.rate >= MIN_EDGE and wilson_lower(stat.hits, stat.samples) > 0.5
            else "NOT reliable (close to coin flip or worse)"
        )
        notes.append(
            f"Pattern {p.name} ({side} bias) on last {tf} candle: next candle moved its way "
            f"{stat.rate:.0%} of {stat.samples} past cases — {verdict}."
        )
    return notes


def chart_read_note(
    frames: dict[Timeframe, pd.DataFrame], instrument: Instrument, tf: Timeframe, spread: float
) -> str:
    read = read_chart(frames, instrument, tf, spread_pips=spread)
    closes = [e.result_pips or 0.0 for e in read.events if e.action == "CLOSE"]
    note = f"Code chart read on {tf}: {read.lean.upper()} (score {read.score:+.1f})."
    if closes:
        wins = sum(p > 0 for p in closes)
        note += (
            f" Following this read in the shown history: {wins}/{len(closes)} cycles profitable, "
            f"net {sum(closes):+.0f} pips."
        )
    return note


async def ai_track_record(session: AsyncSession, symbol: str, now: datetime) -> str | None:
    total, wins, pips = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Signal.result_pips > 0),
                func.coalesce(func.sum(Signal.result_pips), 0.0),
            ).where(
                *signals_repo.source_filter("ai"),
                Signal.symbol == symbol,
                Signal.action.in_(["BUY", "SELL"]),
                Signal.result_pips.is_not(None),
                Signal.closed_at >= now - timedelta(days=TRACK_RECORD_DAYS),
            )
        )
    ).one()
    if not total:
        return None
    return (
        f"Your own closed {symbol} trades, last {TRACK_RECORD_DAYS} days: {wins}/{total} "
        f"profitable, net {float(pips):+.0f} pips."
    )


async def history_evidence(
    session: AsyncSession,
    redis: Redis,
    instrument: Instrument,
    frames: dict[Timeframe, pd.DataFrame],
    tf: Timeframe,
    spread: float,
    now: datetime | None = None,
) -> list[str]:
    """`frames` berisi indikator untuk `tf`, H1 dan H4 (candle tertutup)."""
    now = now or datetime.now(UTC)
    stats = await get_pattern_stats(session, redis, instrument.symbol, tf)
    notes = pattern_notes(frames[tf], stats, tf)
    notes.append(chart_read_note(frames, instrument, tf, spread))
    if record := await ai_track_record(session, instrument.symbol, now):
        notes.append(record)
    return notes
