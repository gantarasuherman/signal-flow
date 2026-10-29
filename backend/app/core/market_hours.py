"""Jam buka pasar forex/emas.

Forex & emas spot buka Minggu 17:00 dan tutup Jumat 17:00 waktu New York (otomatis
mengikuti DST). Emas punya jeda harian 17:00–18:00 New York. Libur 25 Des & 1 Jan
diperlakukan tutup sehari penuh (perkiraan; jadwal broker bisa sedikit berbeda).
"""

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.core.timeframes import Timeframe, floor_to_timeframe, last_closed_candle_open

AssetClass = Literal["forex", "metal", "index", "crypto", "commodity"]

NEW_YORK = ZoneInfo("America/New_York")
ROLLOVER_MINUTE = 17 * 60  # 17:00 New York
METAL_BREAK_END_MINUTE = 18 * 60
FULL_DAY_HOLIDAYS = {(12, 25), (1, 1)}
CHECK_STEP = timedelta(minutes=15)


def is_market_open(asset_class: str, ts: datetime) -> bool:
    if asset_class == "crypto":
        return True
    ny = ts.astimezone(NEW_YORK)
    minute = ny.hour * 60 + ny.minute
    weekday = ny.weekday()  # Senin = 0

    if (ny.month, ny.day) in FULL_DAY_HOLIDAYS:
        return False
    if weekday == 5:
        return False
    if weekday == 4 and minute >= ROLLOVER_MINUTE:
        return False
    if weekday == 6 and minute < ROLLOVER_MINUTE:
        return False
    return not (asset_class == "metal" and ROLLOVER_MINUTE <= minute < METAL_BREAK_END_MINUTE)


def candle_has_trading(asset_class: str, open_time: datetime, timeframe: Timeframe) -> bool:
    """True bila ada jam pasar buka di dalam rentang candle."""
    step = min(timeframe.delta, CHECK_STEP)
    end = open_time + timeframe.delta
    t = open_time
    while t < end:
        if is_market_open(asset_class, t):
            return True
        t += step
    return False


def last_expected_candle_open(
    asset_class: str,
    now: datetime,
    timeframe: Timeframe,
    max_lookback: timedelta = timedelta(days=10),
) -> datetime | None:
    """Candle tertutup terakhir yang seharusnya ada datanya (melewati weekend/libur)."""
    t = last_closed_candle_open(now, timeframe)
    limit = now - max_lookback
    while t > limit:
        if candle_has_trading(asset_class, t, timeframe):
            return t
        t -= timeframe.delta
    return None


def next_market_open(
    asset_class: str, now: datetime, horizon: timedelta = timedelta(days=8)
) -> datetime | None:
    if is_market_open(asset_class, now):
        return now
    t = floor_to_timeframe(now, Timeframe.M15) + CHECK_STEP
    end = now + horizon
    while t < end:
        if is_market_open(asset_class, t):
            return t
        t += CHECK_STEP
    return None
