"""Test integrasi ke PostgreSQL (dilewati otomatis bila database tidak tersedia)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.providers.mock import MockProvider
from app.repositories import candles as candles_repo
from app.services.candle_sync import sync_candles

TEST_SYMBOL = "TESTEURUSD"


async def test_sync_then_incremental(db_session: AsyncSession, eurusd: Instrument) -> None:
    session = db_session
    instrument = eurusd.model_copy(update={"symbol": TEST_SYMBOL})
    now = datetime(2026, 10, 28, 6, 5, tzinfo=UTC)
    provider = MockProvider(clock=lambda: now)

    first = await sync_candles(session, provider, instrument, Timeframe.M15, now)
    assert first.up_to_date
    assert first.latest_open_time == datetime(2026, 10, 28, 5, 45, tzinfo=UTC)
    assert first.stored == 1499  # 1500 dari provider, 1 masih berjalan

    # Satu jam kemudian: hanya candle baru (plus candle terakhir yang diambil ulang)
    later = now + timedelta(hours=1)
    provider_later = MockProvider(clock=lambda: later)
    second = await sync_candles(session, provider_later, instrument, Timeframe.M15, later)
    assert second.stored == 5
    assert second.latest_open_time == datetime(2026, 10, 28, 6, 45, tzinfo=UTC)

    # Upsert idempoten: tidak ada duplikat
    rows = await candles_repo.get_candles(session, TEST_SYMBOL, Timeframe.M15, limit=5000)
    assert len(rows) == 1503
    assert rows[-1].open_time == second.latest_open_time

    # Sudah terbaru: tidak ada request ulang
    third = await sync_candles(session, provider_later, instrument, Timeframe.M15, later)
    assert third.stored == 0 and third.up_to_date
