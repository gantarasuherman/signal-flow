"""Backtest strategi pada candle historis di database.

- Memakai `replay` → logika keputusan yang sama persis dengan worker live.
- Biaya: spread (saat replay) + slippage (masuk & keluar, merugikan).
- Anti-overfitting: hasil dipisah in-sample (70% awal) vs out-of-sample (30% akhir) dan
  dibagi ke beberapa jendela waktu berurutan. Opsi `optimize` memilih parameter terbaik
  HANYA dari in-sample lalu melaporkan kinerjanya di out-of-sample.
"""

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import AnalysisConfig, get_analysis_config
from app.analysis.replay import ReplayTrade, replay
from app.backtest.metrics import TradeResult, compute_metrics, equity_curve
from app.core.instruments import Instrument, get_instruments
from app.core.timeframes import Timeframe
from app.repositories import candles as candles_repo
from app.repositories import instrument_settings as settings_repo
from app.services.signal_engine import candles_to_frame
from app.strategies import create_strategy

logger = logging.getLogger(__name__)

# Data sebelum periode uji agar indikator (EMA 200 di H4) sudah valid sejak hari pertama
WARMUP = {
    Timeframe.M15: timedelta(days=10),
    Timeframe.H1: timedelta(days=30),
    Timeframe.H4: timedelta(days=120),
}
# Grid optimasi per strategi (dipilih di in-sample, dilaporkan di out-of-sample)
OPTIMIZE_GRIDS: dict[str, dict[str, list[Any]]] = {
    "trend_pullback": {"sl_atr": [1.5, 2.0], "tp_atr": [3.0, 4.0], "min_triggers": [2, 3]},
    "session_breakout": {"rr": [2.0, 3.0], "trend_filter": ["h4", "none"]},
    "donchian_breakout": {"lookback": [20, 40], "sl_atr": [1.5, 2.5]},
}
MIN_TRADES_FOR_SELECTION = 15
MAX_TRADES_IN_REPORT = 300


class BacktestRequest(BaseModel):
    symbols: list[str] | None = Field(default=None, description="Kosong = semua instrumen aktif")
    days: int = Field(default=365, ge=30, le=1100)
    in_sample_ratio: float = Field(default=0.7, ge=0.5, le=0.9)
    windows: int = Field(default=4, ge=2, le=12)
    risk_percent: float = Field(default=1.0, gt=0, le=10)
    optimize: bool = False


@dataclass
class InstrumentData:
    instrument: Instrument
    frames: dict[Timeframe, pd.DataFrame]
    spread_pips: float
    slippage_pips: float
    coverage: dict[str, Any] = field(default_factory=dict)


def to_trade_results(
    trades: list[ReplayTrade], instrument: Instrument, spread_pips: float, slippage_pips: float
) -> list[TradeResult]:
    out = []
    pip = instrument.pip_size
    for t in trades:
        if t.result_pips is None or t.exit_time is None:
            continue  # masih terbuka di akhir periode
        sl_pips = abs(t.entry - t.stop_loss) / pip
        tp_pips = abs(t.take_profit - t.entry) / pip
        out.append(
            TradeResult(
                symbol=instrument.symbol,
                action=t.action,
                entry_time=t.entry_time,
                exit_time=t.exit_time,
                status=t.status,
                result_pips=round(t.result_pips - 2 * slippage_pips, 1),
                risk_pips=sl_pips + spread_pips + slippage_pips,
                planned_rr=round((tp_pips - spread_pips) / (sl_pips + spread_pips), 2),
                close_reason=t.close_reason,
            )
        )
    return out


def _between(trades: list[TradeResult], start: datetime, end: datetime) -> list[TradeResult]:
    return [t for t in trades if start <= t.entry_time < end]


def summarize(
    trades: list[TradeResult], start: datetime, end: datetime, req: BacktestRequest
) -> dict[str, Any]:
    split = start + (end - start) * req.in_sample_ratio
    step = (end - start) / req.windows
    windows = []
    for i in range(req.windows):
        w_start, w_end = start + step * i, start + step * (i + 1)
        m = compute_metrics(
            _between(trades, w_start, w_end), risk_percent=req.risk_percent, period=(w_start, w_end)
        )
        windows.append({"start": w_start.isoformat(), "end": w_end.isoformat(), **m.to_dict()})

    def metrics(a: datetime, b: datetime) -> dict[str, Any]:
        return compute_metrics(
            _between(trades, a, b), risk_percent=req.risk_percent, period=(a, b)
        ).to_dict()

    return {
        "all": metrics(start, end),
        "in_sample": {
            "start": start.isoformat(),
            "end": split.isoformat(),
            **metrics(start, split),
        },
        "out_of_sample": {
            "start": split.isoformat(),
            "end": end.isoformat(),
            **metrics(split, end),
        },
        "windows": windows,
        "equity": equity_curve(trades, req.risk_percent),
    }


def _replay_trades(
    data: InstrumentData,
    strategy_name: str,
    params: dict[str, Any],
    cfg: AnalysisConfig,
    start: datetime,
    end: datetime,
) -> list[TradeResult]:
    strategy = create_strategy(strategy_name, params)
    f = data.frames
    raw = replay(
        strategy,
        data.instrument,
        f[Timeframe.M15],
        f[Timeframe.H1],
        f[Timeframe.H4],
        spread_pips=data.spread_pips,
        filters=cfg.filters,
        max_hold_candles=cfg.max_hold_candles,
        profit_close=cfg.profit_close,
        trailing=cfg.trailing_stop,
        start=start,
    )
    trades = to_trade_results(raw, data.instrument, data.spread_pips, data.slippage_pips)
    return [t for t in trades if t.entry_time < end]


def _optimize(
    data: InstrumentData,
    strategy_name: str,
    base: dict[str, Any],
    cfg: AnalysisConfig,
    start: datetime,
    end: datetime,
    req: BacktestRequest,
) -> dict[str, Any]:
    split = start + (end - start) * req.in_sample_ratio
    grid = []
    space = OPTIMIZE_GRIDS.get(strategy_name, {})
    keys = list(space)
    for values in itertools.product(*space.values()):
        combo = dict(zip(keys, values, strict=True))
        trades = _replay_trades(data, strategy_name, {**base, **combo}, cfg, start, end)
        ins = compute_metrics(_between(trades, start, split), risk_percent=req.risk_percent)
        oos = compute_metrics(_between(trades, split, end), risk_percent=req.risk_percent)
        grid.append({"params": combo, "in_sample": ins.to_dict(), "out_of_sample": oos.to_dict()})

    eligible = [g for g in grid if g["in_sample"]["trades"] >= MIN_TRADES_FOR_SELECTION]
    best = max(eligible or grid, key=lambda g: g["in_sample"]["expectancy_r"] or -99)
    return {
        "note": "Parameter dipilih hanya dari data in-sample; lihat hasil out-of-sample-nya.",
        "best_params": best["params"],
        "best_in_sample": best["in_sample"],
        "best_out_of_sample": best["out_of_sample"],
        "grid": grid,
    }


def compute_backtest(
    datasets: list[InstrumentData],
    specs: dict[str, tuple[str, dict[str, Any]]],
    cfg: AnalysisConfig,
    start: datetime,
    end: datetime,
    req: BacktestRequest,
) -> dict[str, Any]:
    """Bagian CPU-bound (dijalankan di thread terpisah). `specs`: simbol → (strategi, params)."""
    per_instrument: dict[str, Any] = {}
    all_trades: list[TradeResult] = []
    for data in datasets:
        symbol = data.instrument.symbol
        strategy_name, params = specs[symbol]
        trades = _replay_trades(data, strategy_name, params, cfg, start, end)
        all_trades.extend(trades)
        result = summarize(trades, start, end, req)
        result["strategy"] = {"name": strategy_name, "params": params}
        result["coverage"] = data.coverage
        result["costs"] = {"spread_pips": data.spread_pips, "slippage_pips": data.slippage_pips}
        result["trades"] = [
            {
                "action": t.action,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "status": t.status,
                "result_pips": t.result_pips,
                "r": round(t.r, 2),
                "close_reason": t.close_reason,
            }
            for t in trades[-MAX_TRADES_IN_REPORT:]
        ]
        if req.optimize:
            result["optimization"] = _optimize(data, strategy_name, params, cfg, start, end, req)
        per_instrument[symbol] = result
        logger.info("Backtest %s: %d trade", symbol, len(trades))

    names = sorted({name for name, _ in specs.values()})
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": req.days},
        "strategy": {
            "name": ", ".join(names),
            "per_instrument": {s: n for s, (n, _) in specs.items()},
        },
        "settings": req.model_dump(),
        "notes": [
            "Biaya: spread per instrumen + slippage saat masuk & keluar.",
            "Filter volatilitas & tutup akhir pekan diterapkan; filter berita tidak "
            "(tidak ada histori berita).",
            "SL & TP tersentuh di candle yang sama dianggap kena SL (konservatif).",
            "Hasil masa lalu tidak menjamin hasil di masa depan.",
        ],
        "portfolio": summarize(all_trades, start, end, req),
        "instruments": per_instrument,
    }


async def load_dataset(
    session: AsyncSession, instrument: Instrument, start: datetime, end: datetime
) -> InstrumentData:
    frames: dict[Timeframe, pd.DataFrame] = {}
    coverage: dict[str, Any] = {}
    for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4):
        rows = await candles_repo.get_candles(
            session, instrument.symbol, tf, start=start - WARMUP[tf], end=end, limit=200_000
        )
        frames[tf] = candles_to_frame(rows)
        coverage[tf.value] = {
            "candles": len(rows),
            "first": rows[0].open_time.isoformat() if rows else None,
            "last": rows[-1].open_time.isoformat() if rows else None,
        }
    setting = (await settings_repo.get_all(session)).get(instrument.symbol)
    spread = (
        setting.spread_pips
        if setting and setting.spread_pips is not None
        else instrument.typical_spread_pips
    )
    return InstrumentData(instrument, frames, spread, instrument.slippage_pips, coverage)


async def run_backtest(session: AsyncSession, req: BacktestRequest) -> dict[str, Any]:
    instruments = get_instruments()
    symbols = [s.upper() for s in req.symbols] if req.symbols else sorted(instruments)
    unknown = [s for s in symbols if s not in instruments]
    if unknown:
        raise ValueError(f"Instrumen tidak dikenal: {unknown}")

    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=req.days)
    datasets = []
    for symbol in symbols:
        data = await load_dataset(session, instruments[symbol], start, end)
        if len(data.frames[Timeframe.M15]) < 500:
            raise ValueError(
                f"Data {symbol} M15 belum cukup ({len(data.frames[Timeframe.M15])} candle). "
                f"Jalankan: python -m app.cli backfill --timeframe M15 --days {req.days}"
            )
        datasets.append(data)

    cfg = get_analysis_config()
    specs = {symbol: cfg.spec_for(symbol) for symbol in symbols}
    return await asyncio.to_thread(compute_backtest, datasets, specs, cfg, start, end, req)
