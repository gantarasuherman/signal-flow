"""Endpoint dashboard, sinyal, dan analisis terbaru."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import SessionDep, resolve_instrument
from app.core.config import ai_signals_enabled
from app.core.instruments import get_instrument, get_instruments
from app.core.redis import get_redis
from app.core.timeframes import Timeframe, next_candle_close
from app.db.models import Signal
from app.repositories import instrument_settings as settings_repo
from app.repositories import signals as signals_repo
from app.services.risk_prefs import RiskPrefs, get_risk_prefs
from app.services.signal_engine import get_latest_analysis
from app.services.views import InstrumentCard, SignalView, build_card, load_signal_view

router = APIRouter(tags=["signals"])

Source = Literal["rule", "ai"]
SourceQuery = Annotated[Source, Query(description="rule = strategi teruji, ai = AI Groq")]


class DashboardResponse(BaseModel):
    server_time: datetime
    next_candle_close: datetime
    seconds_to_next_candle: int
    risk: RiskPrefs
    cards: list[InstrumentCard]
    ai_enabled: bool
    ai_cards: list[InstrumentCard]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(session: SessionDep) -> DashboardResponse:
    """Semua yang dibutuhkan layar utama dalam satu panggilan."""
    now = datetime.now(UTC)
    redis = get_redis()
    settings_map = await settings_repo.get_all(session)
    prefs = await get_risk_prefs(session)
    instruments = sorted(get_instruments().items())
    cards = [
        await build_card(session, redis, inst, settings_map.get(sym), prefs, now)
        for sym, inst in instruments
    ]
    ai_enabled = ai_signals_enabled()
    ai_cards = (
        [
            await build_card(session, redis, inst, settings_map.get(sym), prefs, now, "ai")
            for sym, inst in instruments
        ]
        if ai_enabled
        else []
    )
    next_close = next_candle_close(now, Timeframe.M15)
    return DashboardResponse(
        server_time=now,
        next_candle_close=next_close,
        seconds_to_next_candle=int((next_close - now).total_seconds()),
        risk=prefs,
        cards=cards,
        ai_enabled=ai_enabled,
        ai_cards=ai_cards,
    )


@router.get("/signals/latest", response_model=InstrumentCard)
async def latest_signal(
    session: SessionDep,
    symbol: Annotated[str, Query(examples=["XAUUSD"])],
    source: SourceQuery = "rule",
) -> InstrumentCard:
    """Kartu sinyal terbaru untuk satu instrumen (aksi, entry/SL/TP, status, lot)."""
    instrument = resolve_instrument(symbol)
    setting = (await settings_repo.get_all(session)).get(instrument.symbol)
    prefs = await get_risk_prefs(session)
    return await build_card(
        session, get_redis(), instrument, setting, prefs, datetime.now(UTC), source
    )


async def _views(session: SessionDep, rows: list[Signal]) -> list[SignalView]:
    now = datetime.now(UTC)
    redis = get_redis()
    settings_map = await settings_repo.get_all(session)
    prefs = await get_risk_prefs(session)
    views = []
    for row in rows:
        instrument = get_instrument(row.symbol)
        if instrument is None:  # instrumen sudah dihapus dari konfigurasi
            continue
        views.append(
            await load_signal_view(
                session, redis, row, instrument, settings_map.get(row.symbol), prefs, now
            )
        )
    return views


@router.get("/signals", response_model=list[SignalView])
@router.get("/signals/history", response_model=list[SignalView], include_in_schema=False)
async def list_signals(
    session: SessionDep,
    symbol: Annotated[str | None, Query(examples=["XAUUSD"])] = None,
    action: Annotated[list[str] | None, Query(description="BUY / SELL / CLOSE")] = None,
    status: Annotated[
        list[str] | None, Query(description="ACTIVE / HIT_TP / HIT_SL / CLOSED")
    ] = None,
    before_id: Annotated[
        int | None, Query(description="Paginasi: id terkecil halaman sebelumnya")
    ] = None,
    source: Annotated[Source | None, Query(description="rule / ai (kosong = semua)")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SignalView]:
    """Riwayat sinyal, terbaru dulu."""
    rows = await signals_repo.list_recent(
        session,
        symbol=symbol.upper() if symbol else None,
        actions=[a.upper() for a in action] if action else None,
        statuses=[s.upper() for s in status] if status else None,
        before_id=before_id,
        source=source,
        limit=limit,
    )
    return await _views(session, rows)


@router.get("/signals/{signal_id}", response_model=SignalView)
async def get_signal(signal_id: int, session: SessionDep) -> SignalView:
    row = await session.get(Signal, signal_id)
    if row is None:
        raise HTTPException(404, f"Sinyal {signal_id} tidak ditemukan")
    views = await _views(session, [row])
    if not views:
        raise HTTPException(404, f"Instrumen {row.symbol} sudah tidak aktif")
    return views[0]


@router.get("/analysis/latest")
async def latest_analysis(
    symbol: Annotated[str | None, Query(examples=["XAUUSD"])] = None,
    source: SourceQuery = "rule",
) -> list[dict[str, Any]]:
    """Hasil analisis mentah terakhir per instrumen (untuk debugging)."""
    symbols = [resolve_instrument(symbol).symbol] if symbol else sorted(get_instruments())
    redis = get_redis()
    results = [await get_latest_analysis(redis, s, source) for s in symbols]
    return [r for r in results if r]
