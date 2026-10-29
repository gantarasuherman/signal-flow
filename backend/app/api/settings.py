from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.core.instruments import get_instruments
from app.core.redis import get_redis
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
