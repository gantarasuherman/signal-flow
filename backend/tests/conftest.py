from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.instruments import Instrument
from app.db.models import Candle, InstrumentSetting, Signal

TEST_PREFIX = "TEST"


@pytest.fixture
def xauusd() -> Instrument:
    return Instrument(
        symbol="XAUUSD",
        provider_symbol="XAU/USD",
        name="Emas",
        asset_class="metal",
        pip_size=0.1,
        digits=2,
        contract_size=100,
        quote_currency="USD",
        typical_spread_pips=2.5,
        signal_validity_pips=15,
    )


@pytest.fixture
def eurusd() -> Instrument:
    return Instrument(
        symbol="EURUSD",
        provider_symbol="EUR/USD",
        name="Euro",
        asset_class="forex",
        pip_size=0.0001,
        digits=5,
        contract_size=100000,
        quote_currency="USD",
        typical_spread_pips=0.8,
        signal_validity_pips=5,
    )


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session ke PostgreSQL compose. Dilewati bila DB tidak tersedia (mis. `--no-deps`).
    Semua data dengan simbol berawalan TEST dihapus setelah test."""
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM signals LIMIT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("PostgreSQL (dengan migrasi terbaru) tidak tersedia")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def cleanup(session: AsyncSession) -> None:
        for model in (Signal, Candle, InstrumentSetting):
            await session.execute(delete(model).where(model.symbol.startswith(TEST_PREFIX)))
        await session.commit()

    async with maker() as session:
        await cleanup(session)
        yield session
        await session.rollback()
        await cleanup(session)
    await engine.dispose()


def make_frame(
    rows: Sequence[dict[str, float]],
    *,
    end: datetime = datetime(2026, 10, 28, 6, 0, tzinfo=UTC),
    step: timedelta = timedelta(minutes=15),
) -> pd.DataFrame:
    """DataFrame berindikator buatan tangan; baris terakhir berwaktu `end`."""
    index = pd.DatetimeIndex([end - step * (len(rows) - 1 - i) for i in range(len(rows))])
    return pd.DataFrame(list(rows), index=index)
