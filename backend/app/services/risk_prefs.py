"""Preferensi risiko pengguna (modal & % risiko), disimpan di server agar sama di HP
dan laptop."""

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.repositories import app_settings as app_settings_repo

RISK_KEY = "risk"


class RiskPrefs(BaseModel):
    capital: float | None = Field(
        default=None, gt=0, description="Modal akun dalam USD (kosong = saran lot tidak dihitung)"
    )
    risk_percent: float = Field(default=1.0, gt=0, le=10, description="% risiko per sinyal")


async def get_risk_prefs(session: AsyncSession) -> RiskPrefs:
    stored = await app_settings_repo.get_value(session, RISK_KEY)
    if stored is None:
        return RiskPrefs(risk_percent=get_settings().default_risk_percent)
    return RiskPrefs.model_validate(stored)


async def save_risk_prefs(session: AsyncSession, prefs: RiskPrefs) -> RiskPrefs:
    await app_settings_repo.set_value(session, RISK_KEY, prefs.model_dump())
    await session.commit()
    return prefs
