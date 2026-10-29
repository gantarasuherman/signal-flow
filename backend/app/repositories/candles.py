from collections.abc import Sequence
from datetime import datetime
from itertools import batched

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeframes import Timeframe
from app.data.schemas import CandleDTO
from app.db.models import Candle

# asyncpg membatasi 32767 parameter per statement (9 kolom x 1000 baris aman)
UPSERT_CHUNK = 1000


async def upsert_candles(
    session: AsyncSession,
    symbol: str,
    timeframe: Timeframe,
    candles: Sequence[CandleDTO],
    source: str,
) -> int:
    for chunk in batched(candles, UPSERT_CHUNK):
        rows = [
            {
                "symbol": symbol,
                "timeframe": timeframe.value,
                "open_time": c.open_time,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "source": source,
            }
            for c in chunk
        ]
        stmt = pg_insert(Candle).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Candle.symbol, Candle.timeframe, Candle.open_time],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "source": stmt.excluded.source,
                "fetched_at": func.now(),
            },
        )
        await session.execute(stmt)
    return len(candles)


async def delete_candles(
    session: AsyncSession, symbol: str, timeframe: Timeframe, open_times: Sequence[datetime]
) -> int:
    deleted = 0
    for chunk in batched(open_times, UPSERT_CHUNK):
        result = await session.execute(
            delete(Candle).where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe.value,
                Candle.open_time.in_(chunk),
            )
        )
        deleted += result.rowcount or 0
    return deleted


async def latest_open_time(
    session: AsyncSession, symbol: str, timeframe: Timeframe
) -> datetime | None:
    stmt = select(func.max(Candle.open_time)).where(
        Candle.symbol == symbol, Candle.timeframe == timeframe.value
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_candles(
    session: AsyncSession,
    symbol: str,
    timeframe: Timeframe,
    *,
    limit: int = 500,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Candle]:
    """Candle terbaru (maks `limit`) dalam rentang, diurutkan naik."""
    stmt = select(Candle).where(Candle.symbol == symbol, Candle.timeframe == timeframe.value)
    if start:
        stmt = stmt.where(Candle.open_time >= start)
    if end:
        stmt = stmt.where(Candle.open_time <= end)
    stmt = stmt.order_by(Candle.open_time.desc()).limit(limit)
    rows = list((await session.execute(stmt)).scalars())
    rows.reverse()
    return rows
