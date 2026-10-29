from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting


async def get_value(session: AsyncSession, key: str) -> Any | None:
    row = await session.get(AppSetting, key)
    return row.value if row else None


async def set_value(session: AsyncSession, key: str, value: Any) -> None:
    stmt = pg_insert(AppSetting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AppSetting.key],
        set_={"value": stmt.excluded.value, "updated_at": func.now()},
    )
    await session.execute(stmt)
