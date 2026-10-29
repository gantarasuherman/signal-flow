from datetime import UTC, datetime, timedelta

import pytest

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.gaps import find_gaps
from app.data.providers.mock import MockProvider
from app.data.schemas import CandleDTO
from app.services.calibration import CalibrationError, adjust_price, compute_offset
from app.services.candle_sync import is_up_to_date, only_closed

T0 = datetime(2026, 10, 28, 2, 0, tzinfo=UTC)  # Rabu, pasar buka
M15 = Timeframe.M15


def test_find_gaps_detects_missing_candle() -> None:
    times = [T0, T0 + M15.delta, T0 + 3 * M15.delta]
    assert find_gaps(times, M15, "forex") == [T0 + 2 * M15.delta]


def test_weekend_is_not_a_gap() -> None:
    friday_last = datetime(2026, 10, 30, 20, 45, tzinfo=UTC)  # 16:45 New York
    sunday_first = datetime(2026, 11, 1, 22, 0, tzinfo=UTC)  # 17:00 New York (EST)
    assert find_gaps([friday_last, sunday_first], M15, "forex") == []


def test_only_closed_drops_running_candle() -> None:
    now = T0 + timedelta(minutes=20)
    candles = [CandleDTO(T0, 1, 1, 1, 1), CandleDTO(T0 + M15.delta, 1, 1, 1, 1)]
    assert [c.open_time for c in only_closed(candles, M15, now)] == [T0]


def test_only_closed_drops_weekend_candles() -> None:
    saturday = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    candles = [CandleDTO(T0, 1, 1, 1, 1), CandleDTO(saturday, 1, 1, 1, 1)]
    now = saturday + timedelta(hours=1)
    assert len(only_closed(candles, M15, now)) == 2
    assert [c.open_time for c in only_closed(candles, M15, now, "forex")] == [T0]


def test_up_to_date_tolerates_alignment() -> None:
    assert is_up_to_date(T0, T0, M15)
    assert not is_up_to_date(T0 - M15.delta, T0, M15)
    assert not is_up_to_date(None, T0, M15)
    assert is_up_to_date(None, None, M15)


def test_compute_offset_and_adjust(xauusd: Instrument) -> None:
    offset = compute_offset(broker_price=4012.35, feed_price=4010.10, digits=xauusd.digits)
    assert offset == 2.25
    assert adjust_price(4000.00, offset, xauusd.digits) == 4002.25


def test_compute_offset_rejects_typo(eurusd: Instrument) -> None:
    with pytest.raises(CalibrationError):
        compute_offset(broker_price=1.6123, feed_price=1.1612, digits=eurusd.digits)


async def test_mock_provider_is_deterministic_and_skips_weekend(eurusd: Instrument) -> None:
    sunday_noon = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    provider = MockProvider(clock=lambda: sunday_noon)
    first = await provider.fetch_candles(eurusd, M15, limit=50)
    second = await provider.fetch_candles(eurusd, M15, limit=50)

    assert first == second
    assert len(first) == 50
    # Pasar tutup hari Minggu siang, jadi candle terakhir adalah Jumat sore
    assert first[-1].open_time == datetime(2026, 10, 30, 20, 45, tzinfo=UTC)
    assert all(c.low <= min(c.open, c.close) and c.high >= max(c.open, c.close) for c in first)
