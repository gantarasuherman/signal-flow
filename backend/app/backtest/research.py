"""Riset strategi: menguji sekumpulan kandidat per instrumen dengan pemisahan
in-sample/out-of-sample, lalu memilih kandidat sesuai aturan di `validation.py`.

Jalankan: python -m app.cli research --days 365
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import get_analysis_config
from app.backtest.metrics import compute_metrics
from app.backtest.runner import InstrumentData, _between, _replay_trades, load_dataset
from app.backtest.validation import is_validated, select_candidate, validation_reason
from app.core.instruments import get_instruments

logger = logging.getLogger(__name__)

LONDON_NY = list(range(7, 17))  # 07:00–16:59 UTC = 14:00–23:59 WIB


@dataclass(frozen=True)
class Candidate:
    label: str
    strategy: str
    params: dict[str, Any]


CANDIDATES: list[Candidate] = [
    Candidate("pullback (bawaan)", "trend_pullback", {}),
    Candidate("pullback tanpa CLOSE dini", "trend_pullback", {"early_close": False}),
    Candidate(
        "pullback sesi London/NY",
        "trend_pullback",
        {"early_close": False, "entry_hours_utc": LONDON_NY},
    ),
    Candidate(
        "pullback H4 ketat",
        "trend_pullback",
        {"early_close": False, "trend_mode": "h4", "min_triggers": 3, "entry_hours_utc": LONDON_NY},
    ),
    Candidate("breakout sesi Asia + tren H4", "session_breakout", {"trend_filter": "h4"}),
    Candidate("breakout sesi Asia", "session_breakout", {"trend_filter": "none"}),
    Candidate("setup tren dasar", "setup_trend", {}),
    Candidate("setup + konfirmasi candle", "setup_trend", {"confirm_candle": True}),
    Candidate(
        "setup ketat (H4+candle+jarak)",
        "setup_trend",
        {"strict_h4": True, "confirm_candle": True, "max_extension_atr": 2.0},
    ),
    Candidate(
        "setup ketat sesi London/NY",
        "setup_trend",
        {
            "strict_h4": True,
            "confirm_candle": True,
            "max_extension_atr": 2.0,
            "entry_hours_utc": LONDON_NY,
        },
    ),  # fmt: skip
    Candidate("setup + pola candlestick", "setup_trend", {"pattern_confirm": True}),
    Candidate(
        "setup ketat + pola candlestick",
        "setup_trend",
        {"strict_h4": True, "pattern_confirm": True, "max_extension_atr": 2.0},
    ),
    Candidate("pola candle + tren H1 (S/R)", "candle_pattern", {}),
    Candidate(
        "pola candle kuat + H1/H4",
        "candle_pattern",
        {"trend_filter": "h1_h4", "min_strength": 3},
    ),
    Candidate("pola candle sesi London/NY", "candle_pattern", {"entry_hours_utc": LONDON_NY}),
    Candidate(
        "pola pembalikan di S/R (tanpa tren)",
        "candle_pattern",
        {"trend_filter": "none", "min_strength": 2},
    ),
    Candidate("donchian 20", "donchian_breakout", {}),
    Candidate(
        "donchian 40 + H1", "donchian_breakout", {"lookback": 40, "require_h1": True, "sl_atr": 2.5}
    ),
]


def research_instrument(
    data: InstrumentData,
    start: datetime,
    end: datetime,
    in_sample_ratio: float,
    candidates: list[Candidate] | None = None,
) -> dict[str, Any]:
    cfg = get_analysis_config()
    split = start + (end - start) * in_sample_ratio
    results = []
    for c in candidates or CANDIDATES:
        params = {**cfg.strategies.get(c.strategy, {}), **c.params}
        trades = _replay_trades(data, c.strategy, params, cfg, start, end)
        results.append(
            {
                "label": c.label,
                "strategy": c.strategy,
                "params": c.params,
                "in_sample": compute_metrics(_between(trades, start, split)).to_dict(),
                "out_of_sample": compute_metrics(_between(trades, split, end)).to_dict(),
            }
        )
        logger.info("Riset %s · %s: %d trade", data.instrument.symbol, c.label, len(trades))
    chosen = select_candidate(results)
    return {
        "candidates": results,
        "chosen": chosen,
        "validated": bool(chosen and is_validated(chosen["out_of_sample"], chosen["in_sample"])),
        "reason": validation_reason(chosen["out_of_sample"], chosen["in_sample"])
        if chosen
        else "Tidak ada kandidat dengan trade in-sample cukup.",
    }


async def run_research(
    session: AsyncSession,
    symbols: list[str] | None,
    days: int,
    in_sample_ratio: float = 0.7,
    only: str | None = None,
) -> dict[str, Any]:
    """`only`: hanya kandidat yang label/nama strateginya mengandung teks ini."""
    candidates = [
        c for c in CANDIDATES if not only or only in c.label or only == c.strategy
    ] or None
    instruments = get_instruments()
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    out: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat(), "instruments": {}}
    for symbol in symbols or sorted(instruments):
        data = await load_dataset(session, instruments[symbol], start, end)
        out["instruments"][symbol] = await asyncio.to_thread(
            research_instrument, data, start, end, in_sample_ratio, candidates
        )
    return out
