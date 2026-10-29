"""Analisis AI sesuai permintaan: dijalankan hanya saat pengguna menekan tombol
"Analisis AI" untuk instrumen yang sedang dibuka."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.analysis.config import get_analysis_config
from app.api.deps import ProviderDep, SessionDep, resolve_instrument
from app.core.config import ai_signals_enabled
from app.core.redis import get_redis
from app.core.timeframes import Timeframe
from app.repositories import instrument_settings as settings_repo
from app.services.candle_sync import refresh_if_stale
from app.services.risk_prefs import get_risk_prefs
from app.services.signal_engine import (
    analysis_timeframes,
    analyze_instrument,
    resolve_timeframe,
)
from app.services.views import InstrumentCard, build_card
from app.strategies import create_strategy

router = APIRouter(tags=["ai"])

# Jeda minimal antar analisis per instrumen (hemat kuota token harian Groq)
COOLDOWN_SECONDS = 45
BUSY_TTL_SECONDS = 180


class AiAnalysisResponse(BaseModel):
    card: InstrumentCard
    warning: str | None
    cooldown_seconds: int


def ai_warning(symbol: str) -> str | None:
    if get_analysis_config().ai_enabled_for(symbol):
        return None
    return (
        f"Uji historis menunjukkan AI lebih sering salah untuk {symbol} (lebih buruk daripada "
        "tanpa AI). Gunakan hanya sebagai bahan pertimbangan, di akun demo."
    )


@router.post("/analysis/ai", response_model=AiAnalysisResponse)
async def run_ai_analysis(
    session: SessionDep,
    provider: ProviderDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
    votes: Annotated[
        int | None,
        Query(ge=1, le=5, description="Jumlah suara AI; 1 = cepat (analisis 4 sekaligus)"),
    ] = None,
    timeframe: Annotated[
        Timeframe,
        Query(description="Timeframe entry M1–H4; posisi AI aktif tetap di timeframe-nya"),
    ] = Timeframe.M15,
) -> AiAnalysisResponse:
    """Minta keputusan AI Groq sekarang: BUY / SELL / WAIT, atau HOLD / CLOSE untuk posisi
    AI yang sedang aktif. Butuh ±10–30 detik (3 suara AI)."""
    if not ai_signals_enabled():
        raise HTTPException(
            400, "AI Groq tidak aktif (GROQ_API_KEY kosong / AI_SIGNALS_ENABLED=false)"
        )
    instrument = resolve_instrument(symbol)
    redis = get_redis()

    wait = await redis.ttl(f"ai:cooldown:{instrument.symbol}")
    if wait and wait > 0:
        raise HTTPException(
            429,
            f"Tunggu {wait} detik sebelum menganalisis {instrument.symbol} lagi.",
            headers={"Retry-After": str(wait)},
        )
    if not await redis.set(f"ai:busy:{instrument.symbol}", "1", nx=True, ex=BUSY_TTL_SECONDS):
        raise HTTPException(
            409, f"Analisis AI {instrument.symbol} sedang berjalan, tunggu sebentar."
        )

    try:
        now = datetime.now(UTC)
        timeframe = await resolve_timeframe(session, instrument.symbol, "ai", timeframe)
        for tf in analysis_timeframes(timeframe):
            await refresh_if_stale(session, provider, redis, instrument, tf, now)
        cfg = get_analysis_config()
        # Atas permintaan pengguna: AI selalu ditanya (tanpa saringan calon setup)
        params = {**cfg.strategies.get("ai_groq", {}), "prefilter": False, "passive": False}
        if votes is not None:
            params["votes"] = votes
        await analyze_instrument(
            session,
            redis,
            instrument,
            now,
            strategy=create_strategy("ai_groq", params),
            timeframe=timeframe,
        )
        await redis.set(f"ai:cooldown:{instrument.symbol}", "1", ex=COOLDOWN_SECONDS)
    finally:
        await redis.delete(f"ai:busy:{instrument.symbol}")

    setting = (await settings_repo.get_all(session)).get(instrument.symbol)
    prefs = await get_risk_prefs(session)
    card = await build_card(session, redis, instrument, setting, prefs, datetime.now(UTC), "ai")
    return AiAnalysisResponse(
        card=card, warning=ai_warning(instrument.symbol), cooldown_seconds=COOLDOWN_SECONDS
    )


@router.get("/analysis/ai/warning")
async def get_ai_warning(
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
) -> dict[str, str | None]:
    return {"warning": ai_warning(resolve_instrument(symbol).symbol)}
