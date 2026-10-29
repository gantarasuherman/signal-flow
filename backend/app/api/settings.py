from fastapi import APIRouter

from app.api.deps import SessionDep
from app.services.risk_prefs import RiskPrefs, get_risk_prefs, save_risk_prefs

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/risk", response_model=RiskPrefs)
async def read_risk(session: SessionDep) -> RiskPrefs:
    return await get_risk_prefs(session)


@router.put("/risk", response_model=RiskPrefs)
async def update_risk(body: RiskPrefs, session: SessionDep) -> RiskPrefs:
    """Modal (USD) dan % risiko untuk saran ukuran lot di setiap kartu sinyal."""
    return await save_risk_prefs(session, body)
