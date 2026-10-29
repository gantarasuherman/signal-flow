"""Sinkronisasi candle dari provider ke database."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.instruments import Instrument
from app.core.market_hours import candle_has_trading, last_expected_candle_open
from app.core.timeframes import Timeframe
from app.data.errors import ProviderError, RateLimitError
from app.data.gaps import find_gaps
from app.data.providers.base import MAX_BATCH, DataProvider
from app.data.schemas import CandleDTO
from app.repositories import candles as candles_repo

logger = logging.getLogger(__name__)

# Jumlah candle awal: cukup untuk pemanasan EMA 200 di semua timeframe
INITIAL_LIMIT = {
    Timeframe.M1: 500,
    Timeframe.M5: 500,
    Timeframe.M15: 1500,
    Timeframe.H1: 1000,
    Timeframe.H4: 600,
}
# Timeframe yang tidak dijadwalkan worker; isi ulang data bolongnya tidak sepadan dengan kuota
NO_GAP_REFILL = {Timeframe.M1, Timeframe.M5}
# Jeda minimal antar sinkronisasi on-demand dari API (detik)
ON_DEMAND_TTL = {
    Timeframe.M1: 50,
    Timeframe.M5: 120,
    Timeframe.M15: 300,
    Timeframe.H1: 600,
    Timeframe.H4: 1200,
}


@dataclass
class SyncResult:
    symbol: str
    timeframe: Timeframe
    stored: int
    latest_open_time: datetime | None
    up_to_date: bool
    gaps: list[datetime] = field(default_factory=list)


def only_closed(
    candles: Sequence[CandleDTO],
    timeframe: Timeframe,
    now: datetime,
    asset_class: str | None = None,
) -> list[CandleDTO]:
    """Candle yang sudah tutup. Bila `asset_class` diberikan, candle di luar jam pasar
    (mis. akhir pekan — Twelve Data tetap mengirimnya) ikut dibuang."""
    return [
        c
        for c in candles
        if c.open_time + timeframe.delta <= now
        and (asset_class is None or candle_has_trading(asset_class, c.open_time, timeframe))
    ]


def is_up_to_date(latest: datetime | None, expected: datetime | None, timeframe: Timeframe) -> bool:
    """Toleran terhadap perbedaan penjajaran candle provider (mis. H4)."""
    if expected is None:
        return True
    return latest is not None and latest + timeframe.delta > expected


async def sync_candles(
    session: AsyncSession,
    provider: DataProvider,
    instrument: Instrument,
    timeframe: Timeframe,
    now: datetime,
) -> SyncResult:
    symbol = instrument.symbol
    latest = await candles_repo.latest_open_time(session, symbol, timeframe)
    expected = last_expected_candle_open(instrument.asset_class, now, timeframe)
    if is_up_to_date(latest, expected, timeframe):
        return SyncResult(symbol, timeframe, 0, latest, up_to_date=True)

    if latest is None:
        fetched = await provider.fetch_candles(
            instrument, timeframe, limit=INITIAL_LIMIT[timeframe]
        )
    else:
        # Ambil ulang candle terakhir juga, untuk mengoreksi nilai yang mungkin berubah
        fetched = await provider.fetch_candles(instrument, timeframe, start=latest, limit=MAX_BATCH)
    closed = only_closed(fetched, timeframe, now, instrument.asset_class)
    stored = await candles_repo.upsert_candles(session, symbol, timeframe, closed, provider.name)

    times = {c.open_time for c in closed}
    if latest:
        times.add(latest)
    gaps = find_gaps(times, timeframe, instrument.asset_class)
    if gaps and timeframe not in NO_GAP_REFILL:
        refetch = await provider.fetch_candles(
            instrument,
            timeframe,
            start=gaps[0] - timeframe.delta,
            end=gaps[-1] + timeframe.delta,
            limit=MAX_BATCH,
        )
        missing = set(gaps)
        refilled = [
            c
            for c in only_closed(refetch, timeframe, now, instrument.asset_class)
            if c.open_time in missing
        ]
        stored += await candles_repo.upsert_candles(
            session, symbol, timeframe, refilled, provider.name
        )
        gaps = sorted(missing - {c.open_time for c in refilled})
    if gaps:
        logger.warning(
            "%s %s: %d candle bolong dari provider (pertama %s)",
            symbol,
            timeframe,
            len(gaps),
            gaps[0].isoformat(),
        )
    await session.commit()

    new_latest = max(times) if times else None
    result = SyncResult(
        symbol, timeframe, stored, new_latest, is_up_to_date(new_latest, expected, timeframe), gaps
    )
    logger.info(
        "Sync %s %s: %d candle disimpan, terakhir %s%s",
        symbol,
        timeframe,
        stored,
        new_latest.isoformat() if new_latest else "-",
        "" if result.up_to_date else " (belum terbaru)",
    )
    return result


async def refresh_if_stale(
    session: AsyncSession,
    provider: DataProvider,
    redis: Redis,
    instrument: Instrument,
    timeframe: Timeframe,
    now: datetime,
) -> str | None:
    """Sinkronisasi on-demand untuk grafik. Mengembalikan pesan peringatan bila gagal."""
    latest = await candles_repo.latest_open_time(session, instrument.symbol, timeframe)
    expected = last_expected_candle_open(instrument.asset_class, now, timeframe)
    if is_up_to_date(latest, expected, timeframe):
        return None
    throttle_key = f"sync:recent:{instrument.symbol}:{timeframe.value}"
    if not await redis.set(throttle_key, now.isoformat(), nx=True, ex=ON_DEMAND_TTL[timeframe]):
        return None
    try:
        await sync_candles(session, provider, instrument, timeframe, now)
    except RateLimitError as exc:
        await session.rollback()
        return f"Kuota data provider habis, menampilkan data tersimpan. ({exc})"
    except ProviderError as exc:
        await session.rollback()
        logger.warning("Refresh on-demand %s %s gagal: %s", instrument.symbol, timeframe, exc)
        return f"Gagal memperbarui data: {exc}"
    return None
