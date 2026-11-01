"""Uji maju prediksi pola candlestick: setiap prediksi dicatat SAAT pola muncul, lalu hasilnya
diisi setelah candle prediksi tutup. Berbeda dengan tanda ✓/✗ di grafik (dihitung ulang dari
histori yang juga dipakai memilih pola), hanya prediksi yang tercatat tepat waktu (`on_time`)
yang dihitung di sini, sehingga angkanya tidak bisa "melihat masa depan".

Aturannya sama dengan grafik: pola berarah yang di histori instrumen & timeframe ini benar
>= MIN_EDGE dan lolos uji 95%; masuk di awal candle berikutnya, CLOSE di akhir candle ke-N
(N = lama tahan dengan rata-rata untung terbesar di histori, 1 bila tidak ada),
hasil = close candle ke-N - close candle pola, dikurangi spread."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.indicators import compute_indicators
from app.core.instruments import Instrument, get_instruments
from app.core.market_hours import last_expected_candle_open
from app.core.timeframes import Timeframe
from app.db.models import Candle, PatternPrediction
from app.repositories import candles as candles_repo
from app.services.candle_sync import is_up_to_date
from app.services.pattern_stats import best_exit, get_pattern_stats, is_proven
from app.services.signal_engine import candles_to_frame
from app.strategies.common import row_trend
from app.strategies.patterns import read_patterns

logger = logging.getLogger(__name__)

FRAME_BARS = 300
NO_DATA_AFTER = timedelta(days=5)


def on_time_limit(entry_time: datetime, timeframe: Timeframe) -> datetime:
    """Batas pencatatan agar dianggap tepat waktu: awal candle prediksi + 20% durasinya
    (minimal 30 detik) — masih sempat diikuti, hasil belum diketahui."""
    return entry_time + max(timedelta(seconds=30), timeframe.delta * 0.2)


def result_pips(
    direction: int, entry: float, exit_price: float, instrument: Instrument, spread: float
) -> float:
    return round((exit_price - entry) * direction / instrument.pip_size - spread, 1)


async def record_predictions(
    session: AsyncSession,
    redis: Redis,
    instrument: Instrument,
    timeframe: Timeframe,
    now: datetime,
) -> int:
    """Catat prediksi dari pola di candle tertutup terakhir (bila datanya terbaru)."""
    rows = await candles_repo.get_candles(session, instrument.symbol, timeframe, limit=FRAME_BARS)
    if len(rows) < 60:
        return 0
    last = rows[-1]
    expected = last_expected_candle_open(instrument.asset_class, now, timeframe)
    if not is_up_to_date(last.open_time, expected, timeframe):
        return 0
    df = compute_indicators(candles_to_frame(rows))
    reads = [r for r in read_patterns(df, row_trend(df.iloc[-1])) if r.pattern.bias]
    if not reads:
        return 0
    stats = await get_pattern_stats(session, redis, instrument.symbol, timeframe)
    entry_time = last.open_time + timeframe.delta
    added = 0
    for read in reads:
        stat = stats.get(read.pattern.name)
        if stat is None or not is_proven(stat):
            continue
        plan = best_exit(stat, instrument.pip_size, instrument.typical_spread_pips)
        hold = plan.hold if plan else 1
        stmt = (
            pg_insert(PatternPrediction)
            .values(
                symbol=instrument.symbol,
                timeframe=timeframe.value,
                pattern=read.pattern.name,
                direction=read.pattern.bias,
                chance=round(stat.rate, 4),
                samples=stat.samples,
                pattern_time=last.open_time,
                entry_time=entry_time,
                close_time=entry_time + timeframe.delta * hold,
                entry_price=last.close,
                spread_pips=instrument.typical_spread_pips,
                status="open",
                on_time=now <= on_time_limit(entry_time, timeframe),
            )
            .on_conflict_do_nothing()
            .returning(PatternPrediction.id)
        )
        if (await session.execute(stmt)).scalar_one_or_none() is not None:
            added += 1
    if added:
        logger.info("Prediksi pola dicatat: %s %s (%d)", instrument.symbol, timeframe.value, added)
    return added


async def resolve_predictions(session: AsyncSession, now: datetime) -> int:
    """Isi hasil prediksi yang candle-nya sudah tutup dan tersimpan."""
    rows = (
        await session.execute(
            select(PatternPrediction).where(
                PatternPrediction.status == "open", PatternPrediction.close_time <= now
            )
        )
    ).scalars()
    instruments = get_instruments()
    done = 0
    for p in rows:
        instrument = instruments.get(p.symbol)
        if instrument is None:
            continue
        # Candle ke-N mulai entry_time (melompati jeda pasar, mis. akhir pekan)
        hold = max(1, round((p.close_time - p.entry_time) / Timeframe(p.timeframe).delta))
        candles = (
            (
                await session.execute(
                    select(Candle)
                    .where(
                        Candle.symbol == p.symbol,
                        Candle.timeframe == p.timeframe,
                        Candle.open_time >= p.entry_time,
                    )
                    .order_by(Candle.open_time)
                    .limit(hold)
                )
            )
            .scalars()
            .all()
        )
        candle = candles[-1] if len(candles) == hold else None
        if candle is not None:
            p.exit_price = candle.close
            p.result_pips = result_pips(
                p.direction, p.entry_price, candle.close, instrument, p.spread_pips
            )
            p.status = "done"
            done += 1
        elif now - p.close_time > NO_DATA_AFTER:
            p.status = "no_data"
    return done


async def log_predictions(
    session: AsyncSession, redis: Redis, instrument: Instrument, timeframe: Timeframe, now: datetime
) -> None:
    """Catat + selesaikan, aman dipanggil dari API maupun worker (kegagalan hanya di-log)."""
    try:
        await record_predictions(session, redis, instrument, timeframe, now)
        await resolve_predictions(session, now)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Gagal mencatat prediksi pola %s %s", instrument.symbol, timeframe.value)


async def prediction_summary(
    session: AsyncSession,
    symbol: str | None = None,
    timeframe: Timeframe | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    """Rekap uji maju: hanya prediksi tepat waktu yang sudah ada hasilnya. `days` membatasi ke
    prediksi yang masuk dalam sekian hari terakhir."""
    where = [PatternPrediction.on_time.is_(True)]
    if days:
        where.append(PatternPrediction.entry_time >= datetime.now(UTC) - timedelta(days=days))
    if symbol:
        where.append(PatternPrediction.symbol == symbol)
    if timeframe:
        where.append(PatternPrediction.timeframe == timeframe.value)
    done = [*where, PatternPrediction.status == "done"]
    total, hits, pips = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(PatternPrediction.result_pips > 0),
                func.coalesce(func.sum(PatternPrediction.result_pips), 0.0),
            ).where(*done)
        )
    ).one()
    groups = (
        await session.execute(
            select(
                PatternPrediction.symbol,
                PatternPrediction.timeframe,
                func.count(),
                func.count().filter(PatternPrediction.result_pips > 0),
                func.coalesce(func.sum(PatternPrediction.result_pips), 0.0),
            )
            .where(*done)
            .group_by(PatternPrediction.symbol, PatternPrediction.timeframe)
            .order_by(PatternPrediction.symbol, PatternPrediction.timeframe)
        )
    ).all()
    pending = (
        await session.execute(
            select(func.count()).where(*where, PatternPrediction.status == "open")
        )
    ).scalar_one()
    since = (await session.execute(select(func.min(PatternPrediction.created_at)))).scalar()
    recent = (
        await session.execute(
            select(PatternPrediction)
            .where(*where)
            .order_by(PatternPrediction.entry_time.desc())
            .limit(30)
        )
    ).scalars()
    return {
        "since": since,
        "done": total,
        "hits": hits,
        "pips": round(float(pips), 1),
        "pending": pending,
        "groups": [
            {"symbol": s, "timeframe": tf, "done": n, "hits": h, "pips": round(float(pp), 1)}
            for s, tf, n, h, pp in groups
        ],
        "recent": list(recent),
    }
