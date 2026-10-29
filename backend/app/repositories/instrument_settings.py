from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InstrumentSetting


async def get_all(session: AsyncSession) -> dict[str, InstrumentSetting]:
    rows = (await session.execute(select(InstrumentSetting))).scalars()
    return {row.symbol: row for row in rows}


async def get_or_create(session: AsyncSession, symbol: str) -> InstrumentSetting:
    setting = await session.get(InstrumentSetting, symbol)
    if setting is None:
        setting = InstrumentSetting(symbol=symbol, price_offset=0.0)
        session.add(setting)
    return setting
