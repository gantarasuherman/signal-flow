"""Mode AI otomatis: worker meminta keputusan AI setiap candle M15 tanpa menekan tombol."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import app_settings

AI_AUTO_SETTING = "ai_auto"


async def ai_auto_enabled(session: AsyncSession) -> bool:
    return bool(await app_settings.get_value(session, AI_AUTO_SETTING))
