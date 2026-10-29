from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.timeframes import (
    Timeframe,
    floor_to_timeframe,
    last_closed_candle_open,
    next_candle_close,
)

WIB = ZoneInfo("Asia/Jakarta")


def test_floor_m15() -> None:
    ts = datetime(2026, 10, 29, 8, 44, 59, tzinfo=UTC)
    assert floor_to_timeframe(ts, Timeframe.M15) == datetime(2026, 10, 29, 8, 30, tzinfo=UTC)


def test_last_closed_candle_just_after_close() -> None:
    # Worker berjalan pukul 15:45:10 WIB -> candle terakhir yang tutup dibuka 15:30 WIB
    now = datetime(2026, 10, 29, 15, 45, 10, tzinfo=WIB)
    expected = datetime(2026, 10, 29, 15, 30, tzinfo=WIB)
    assert last_closed_candle_open(now, Timeframe.M15) == expected


def test_floor_m5_for_chart() -> None:
    ts = datetime(2026, 10, 29, 8, 14, 30, tzinfo=UTC)
    assert floor_to_timeframe(ts, Timeframe.M5) == datetime(2026, 10, 29, 8, 10, tzinfo=UTC)


def test_h4_aligned_to_utc() -> None:
    ts = datetime(2026, 10, 29, 7, 59, tzinfo=UTC)
    assert floor_to_timeframe(ts, Timeframe.H4) == datetime(2026, 10, 29, 4, 0, tzinfo=UTC)


def test_next_close_for_countdown() -> None:
    now = datetime(2026, 10, 29, 8, 0, 0, tzinfo=UTC)
    assert next_candle_close(now, Timeframe.M15) == datetime(2026, 10, 29, 8, 15, tzinfo=UTC)
