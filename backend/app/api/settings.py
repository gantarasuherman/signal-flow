from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import ProviderDep, SessionDep
from app.core.config import get_settings
from app.core.instruments import get_instruments
from app.core.redis import get_redis
from app.data.providers import (
    DATA_PROVIDER_SETTING,
    PROVIDER_LABELS,
    SwitchableProvider,
    provider_configured,
)
from app.repositories import app_settings
from app.services.risk_prefs import RiskPrefs, get_risk_prefs, save_risk_prefs
from app.services.watch import set_watch_all, watch_all_enabled

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/risk", response_model=RiskPrefs)
async def read_risk(session: SessionDep) -> RiskPrefs:
    return await get_risk_prefs(session)


@router.put("/risk", response_model=RiskPrefs)
async def update_risk(body: RiskPrefs, session: SessionDep) -> RiskPrefs:
    """Modal (USD) dan % risiko untuk saran ukuran lot di setiap kartu sinyal."""
    return await save_risk_prefs(session, body)


class WatchAll(BaseModel):
    enabled: bool


@router.get("/watch-all", response_model=WatchAll)
async def read_watch_all(session: SessionDep) -> WatchAll:
    return WatchAll(enabled=await watch_all_enabled(session))


@router.put("/watch-all", response_model=WatchAll)
async def update_watch_all(body: WatchAll, session: SessionDep) -> WatchAll:
    """Nyala: strategi menganalisis keempat instrumen tiap 15 menit, bukan hanya yang dibuka
    (lebih banyak pemakaian kuota data Twelve Data)."""
    await set_watch_all(session, get_redis(), body.enabled, sorted(get_instruments()))
    return body


class DataProviderOption(BaseModel):
    id: str
    label: str
    configured: bool
    remaining_daily: int | None
    daily_limit: int


class DataProviderState(BaseModel):
    active: str
    options: list[DataProviderOption]


class DataProviderChoice(BaseModel):
    provider: Literal["twelvedata", "tiingo"]


async def _provider_state(provider: SwitchableProvider) -> DataProviderState:
    settings = get_settings()
    limits = {"twelvedata": settings.twelvedata_daily_limit, "tiingo": settings.tiingo_daily_limit}
    return DataProviderState(
        active=await provider.active_name(),
        options=[
            DataProviderOption(
                id=name,
                label=PROVIDER_LABELS[name],
                configured=provider_configured(settings, name),
                remaining_daily=await p.remaining_daily_credits(),
                daily_limit=limits[name],
            )
            for name, p in provider.providers.items()
        ],
    )


def _switchable(provider: object) -> SwitchableProvider:
    if not isinstance(provider, SwitchableProvider):
        raise HTTPException(400, "Sumber data tidak bisa diganti (DATA_PROVIDER=mock)")
    return provider


@router.get("/data-provider", response_model=DataProviderState)
async def read_data_provider(provider: ProviderDep) -> DataProviderState:
    return await _provider_state(_switchable(provider))


@router.put("/data-provider", response_model=DataProviderState)
async def update_data_provider(
    body: DataProviderChoice, session: SessionDep, provider: ProviderDep
) -> DataProviderState:
    """Ganti sumber data candle (Twelve Data / Tiingo). Worker mengikuti dalam ±5 detik.
    Streaming WebSocket Twelve Data untuk harga live tetap berjalan bila tersedia."""
    switchable = _switchable(provider)
    if not provider_configured(get_settings(), body.provider):
        raise HTTPException(400, f"API key {PROVIDER_LABELS[body.provider]} belum diisi di .env")
    await app_settings.set_value(session, DATA_PROVIDER_SETTING, body.provider)
    await session.commit()
    switchable.invalidate()
    return await _provider_state(switchable)
