from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Signal


async def get_active(session: AsyncSession, symbol: str, strategy: str) -> Signal | None:
    stmt = select(Signal).where(
        Signal.symbol == symbol, Signal.strategy == strategy, Signal.status == "ACTIVE"
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def exists(
    session: AsyncSession, symbol: str, strategy: str, candle_time: datetime, action: str
) -> bool:
    stmt = select(Signal.id).where(
        Signal.symbol == symbol,
        Signal.strategy == strategy,
        Signal.candle_time == candle_time,
        Signal.action == action,
    )
    return (await session.execute(stmt)).first() is not None


AI_STRATEGY = "ai_groq"


def source_filter(source: str | None) -> list[Any]:
    """Filter sumber sinyal: 'ai' = strategi AI, 'rule' = strategi aturan, None = semua."""
    if source == "ai":
        return [Signal.strategy == AI_STRATEGY]
    if source == "rule":
        return [Signal.strategy != AI_STRATEGY]
    return []


async def get_active_for_symbol(
    session: AsyncSession, symbol: str, source: str | None = "rule"
) -> Signal | None:
    stmt = (
        select(Signal)
        .where(Signal.symbol == symbol, Signal.status == "ACTIVE", *source_filter(source))
        .order_by(Signal.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_recent(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    actions: list[str] | None = None,
    statuses: list[str] | None = None,
    before_id: int | None = None,
    source: str | None = None,
    limit: int = 50,
) -> list[Signal]:
    """Terbaru dulu. Paginasi dengan `before_id` = id terkecil dari halaman sebelumnya."""
    stmt = select(Signal).where(*source_filter(source)).order_by(Signal.id.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(Signal.symbol == symbol)
    if actions:
        stmt = stmt.where(Signal.action.in_(actions))
    if statuses:
        stmt = stmt.where(Signal.status.in_(statuses))
    if before_id:
        stmt = stmt.where(Signal.id < before_id)
    return list((await session.execute(stmt)).scalars())
