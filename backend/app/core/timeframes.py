"""Utilitas waktu candle (semua perhitungan dalam UTC)."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"

    @property
    def minutes(self) -> int:
        return {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}[self.value]

    @property
    def delta(self) -> timedelta:
        return timedelta(minutes=self.minutes)


def floor_to_timeframe(ts: datetime, timeframe: Timeframe) -> datetime:
    """Waktu buka candle yang memuat `ts`."""
    ts = ts.astimezone(UTC)
    epoch_minutes = int(ts.timestamp() // 60)
    floored = epoch_minutes - (epoch_minutes % timeframe.minutes)
    return datetime.fromtimestamp(floored * 60, tz=UTC)


def last_closed_candle_open(now: datetime, timeframe: Timeframe) -> datetime:
    """Waktu buka candle terakhir yang SUDAH ditutup pada saat `now`."""
    return floor_to_timeframe(now, timeframe) - timeframe.delta


def next_candle_close(now: datetime, timeframe: Timeframe) -> datetime:
    """Waktu tutup candle yang sedang berjalan (untuk countdown)."""
    return floor_to_timeframe(now, timeframe) + timeframe.delta
