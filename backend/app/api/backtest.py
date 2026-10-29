"""Endpoint backtest, status validasi strategi, & statistik sinyal live."""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.analysis.config import get_analysis_config
from app.api.deps import SessionDep
from app.backtest.metrics import TradeResult, compute_metrics, equity_curve
from app.backtest.runner import BacktestRequest
from app.backtest.validation import is_validated, validation_reason
from app.core.instruments import get_instruments
from app.db.models import BacktestRun, Signal
from app.repositories import signals as signals_repo
from app.services.risk_prefs import get_risk_prefs

router = APIRouter(tags=["backtest"])


class BacktestRunOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    request: dict[str, Any]
    error: str | None


class BacktestRunDetail(BacktestRunOut):
    summary: dict[str, Any] | None


@router.post("/backtests", response_model=BacktestRunOut, status_code=202)
async def create_backtest(body: BacktestRequest, session: SessionDep) -> BacktestRunOut:
    """Masukkan backtest ke antrean; worker mengerjakannya (±1 menit per instrumen)."""
    instruments = get_instruments()
    unknown = [s for s in body.symbols or [] if s.upper() not in instruments]
    if unknown:
        raise HTTPException(422, f"Instrumen tidak dikenal: {unknown}")
    busy = (
        await session.execute(
            select(BacktestRun.id).where(BacktestRun.status.in_(["queued", "running"]))
        )
    ).first()
    if busy:
        raise HTTPException(409, f"Backtest #{busy[0]} masih berjalan, tunggu sampai selesai.")
    run = BacktestRun(status="queued", request=body.model_dump())
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return BacktestRunOut.model_validate(run)


@router.get("/backtests", response_model=list[BacktestRunOut])
async def list_backtests(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=50)] = 20
) -> list[BacktestRunOut]:
    rows = (
        await session.execute(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit))
    ).scalars()
    return [BacktestRunOut.model_validate(r) for r in rows]


@router.get("/backtests/{run_id}", response_model=BacktestRunDetail)
async def get_backtest(run_id: int, session: SessionDep) -> BacktestRunDetail:
    run = await session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(404, f"Backtest #{run_id} tidak ditemukan")
    return BacktestRunDetail.model_validate(run)


class StrategyStatus(BaseModel):
    symbol: str
    strategy: str
    tested: bool
    validated: bool
    reason: str
    backtest_id: int | None
    tested_at: datetime | None
    out_of_sample: dict[str, Any] | None


def _same_params(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


@router.get("/strategy/status", response_model=list[StrategyStatus])
async def strategy_status(session: SessionDep) -> list[StrategyStatus]:
    """Apakah strategi yang AKTIF per instrumen sudah lolos uji backtest out-of-sample?"""
    cfg = get_analysis_config()
    runs = (
        await session.execute(
            select(BacktestRun)
            .where(BacktestRun.status == "done")
            .order_by(BacktestRun.id.desc())
            .limit(30)
        )
    ).scalars()
    runs = list(runs)
    out = []
    for symbol in sorted(get_instruments()):
        name, params = cfg.spec_for(symbol)
        if name == "disabled":
            out.append(
                StrategyStatus(
                    symbol=symbol,
                    strategy=name,
                    tested=False,
                    validated=False,
                    reason="Sinyal dinonaktifkan: belum ada strategi yang lolos uji backtest.",
                    backtest_id=None,
                    tested_at=None,
                    out_of_sample=None,
                )
            )
            continue
        # Dari backtest strategi yang sama, pakai periode TERPANJANG (lalu yang terbaru):
        # backtest pendek (mis. 90 hari) tidak boleh menimpa penilaian 1 tahun.
        match = None
        for run in sorted(runs, key=lambda r: (r.request.get("days", 0), r.id), reverse=True):
            result = (run.summary or {}).get("instruments", {}).get(symbol)
            tested = (result or {}).get("strategy")
            if (
                result
                and tested
                and tested["name"] == name
                and _same_params(tested["params"], params)
            ):
                match = (run, result)
                break
        if match is None:
            out.append(
                StrategyStatus(
                    symbol=symbol,
                    strategy=name,
                    tested=False,
                    validated=False,
                    reason="Strategi & parameter ini belum pernah di-backtest.",
                    backtest_id=None,
                    tested_at=None,
                    out_of_sample=None,
                )
            )
            continue
        run, result = match
        oos = result["out_of_sample"]
        out.append(
            StrategyStatus(
                symbol=symbol,
                strategy=name,
                tested=True,
                validated=is_validated(oos, result["in_sample"]),
                reason=validation_reason(oos, result["in_sample"]),
                backtest_id=run.id,
                tested_at=run.finished_at,
                out_of_sample={
                    k: oos.get(k)
                    for k in ("trades", "win_rate", "profit_factor", "expectancy_r", "total_r")
                },
            )
        )
    return out


def signal_to_trade(signal: Signal, pip_size: float) -> TradeResult | None:
    if (
        signal.result_pips is None
        or signal.entry is None
        or signal.stop_loss is None
        or signal.closed_at is None
    ):
        return None
    sl_pips = abs(signal.entry - signal.stop_loss) / pip_size
    return TradeResult(
        symbol=signal.symbol,
        action=signal.action,
        entry_time=signal.candle_time,
        exit_time=signal.closed_at,
        status=signal.status or "CLOSED",
        result_pips=signal.result_pips,
        risk_pips=sl_pips + (signal.spread_pips or 0.0),
        planned_rr=signal.risk_reward,
        close_reason=signal.close_reason,
    )


@router.get("/stats")
async def live_stats(
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=3650)] = 30,
    source: Annotated[
        Literal["rule", "ai"], Query(description="rule = strategi teruji, ai = AI Groq")
    ] = "rule",
) -> dict[str, Any]:
    """Kinerja sinyal LIVE yang sudah selesai (kena TP/SL/ditutup), bila masuk di harga entry."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    rows = (
        await session.execute(
            select(Signal).where(
                Signal.action.in_(["BUY", "SELL"]),
                Signal.status.in_(["HIT_TP", "HIT_SL", "CLOSED"]),
                Signal.closed_at >= start,
                *signals_repo.source_filter(source),
            )
        )
    ).scalars()
    instruments = get_instruments()
    trades = [
        t
        for r in rows
        if r.symbol in instruments and (t := signal_to_trade(r, instruments[r.symbol].pip_size))
    ]
    risk = (await get_risk_prefs(session)).risk_percent
    by_symbol = {
        symbol: compute_metrics(
            [t for t in trades if t.symbol == symbol], risk_percent=risk, period=(start, end)
        ).to_dict()
        for symbol in sorted(instruments)
    }
    return {
        "days": days,
        "source": source,
        "risk_percent": risk,
        "overall": compute_metrics(trades, risk_percent=risk, period=(start, end)).to_dict(),
        "instruments": by_symbol,
        "equity": equity_curve(trades, risk),
    }
