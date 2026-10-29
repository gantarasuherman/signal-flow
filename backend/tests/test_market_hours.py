from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.market_hours import (
    is_market_open,
    last_expected_candle_open,
    next_market_open,
)
from app.core.timeframes import Timeframe

NY = ZoneInfo("America/New_York")
WIB = ZoneInfo("Asia/Jakarta")


def test_weekday_open() -> None:
    assert is_market_open("forex", datetime(2026, 10, 28, 10, 0, tzinfo=NY))  # Rabu


def test_saturday_closed() -> None:
    assert not is_market_open("forex", datetime(2026, 10, 31, 12, 0, tzinfo=NY))


def test_friday_close_and_sunday_open() -> None:
    assert is_market_open("forex", datetime(2026, 10, 30, 16, 59, tzinfo=NY))
    assert not is_market_open("forex", datetime(2026, 10, 30, 17, 0, tzinfo=NY))
    assert not is_market_open("forex", datetime(2026, 11, 1, 16, 59, tzinfo=NY))
    assert is_market_open("forex", datetime(2026, 11, 1, 17, 0, tzinfo=NY))


def test_gold_daily_break_and_sunday_open() -> None:
    assert not is_market_open("metal", datetime(2026, 10, 28, 17, 30, tzinfo=NY))
    assert is_market_open("forex", datetime(2026, 10, 28, 17, 30, tzinfo=NY))
    assert not is_market_open("metal", datetime(2026, 11, 1, 17, 30, tzinfo=NY))
    assert is_market_open("metal", datetime(2026, 11, 1, 18, 0, tzinfo=NY))


def test_crypto_always_open() -> None:
    assert is_market_open("crypto", datetime(2026, 10, 31, 12, 0, tzinfo=NY))


def test_last_expected_candle_skips_weekend() -> None:
    # Sabtu siang WIB: candle M15 terakhir yang seharusnya ada adalah Jumat 16:45 New York
    now = datetime(2026, 10, 31, 12, 0, tzinfo=WIB)
    expected = last_expected_candle_open("forex", now, Timeframe.M15)
    assert expected == datetime(2026, 10, 30, 16, 45, tzinfo=NY).astimezone(UTC)


def test_next_market_open_on_weekend() -> None:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=NY)
    assert next_market_open("forex", now) == datetime(2026, 11, 1, 17, 0, tzinfo=NY)
