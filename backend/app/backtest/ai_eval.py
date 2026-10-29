"""Evaluasi historis sinyal AI: apakah AI menambah nilai dibanding mengambil SEMUA calon
setup dari kode?

Replay candle demi candle (tanpa melihat masa depan). Di setiap calon setup:
- baseline  : selalu masuk (SL 1.5×ATR, TP R:R 2 setelah spread);
- AI        : bertanya ke Groq (dengan `votes`), masuk hanya bila AI setuju.
TP/SL, batas waktu, dan filter sama untuk keduanya. CLOSE dini dari AI tidak dievaluasi
(hemat kuota). Jumlah panggilan dibatasi `max_calls` dan diberi jeda agar tidak melewati
batas token/menit Groq.

Jalankan: python -m app.cli ai-eval --symbols USDJPY --days 30 --max-calls 120
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import get_analysis_config
from app.analysis.engine import step
from app.analysis.filters import volatility_block, weekend_close_block
from app.analysis.indicators import compute_indicators
from app.analysis.replay import ReplayTrade
from app.backtest.metrics import compute_metrics
from app.backtest.runner import load_dataset, to_trade_results
from app.core.instruments import get_instruments
from app.core.market_hours import candle_has_trading
from app.core.timeframes import Timeframe
from app.strategies.ai_groq import AiGroqStrategy
from app.strategies.base import Action, ActiveSignalView, Decision, Strategy, StrategyContext
from app.strategies.common import net_rr, take_profit_distance
from app.strategies.features import potential_setup

logger = logging.getLogger(__name__)


class _NoParams(BaseModel):
    pass


class SetupBaseline(Strategy):
    """Masuk di SETIAP calon setup kode (pembanding tanpa AI)."""

    name = "setup_baseline"
    Params: ClassVar[type[BaseModel]] = _NoParams
    sl_atr: ClassVar[float] = 1.5
    rr: ClassVar[float] = 2.0

    def evaluate(self, ctx: StrategyContext) -> Decision:
        setup = potential_setup(ctx.m15, ctx.h1, ctx.h4)
        if setup is None:
            return Decision(Action.WAIT)
        last = ctx.m15.iloc[-1]
        entry, atr, d = float(last["close"]), float(last["atr"]), setup.direction
        sl = self.sl_atr * atr
        tp = take_profit_distance(sl, ctx.spread_price, self.rr)
        inst = ctx.instrument
        return Decision(
            Action.BUY if d == 1 else Action.SELL,
            entry=inst.round_price(entry),
            stop_loss=inst.round_price(entry - d * sl),
            take_profit=inst.round_price(entry + d * tp),
            confidence=0.5,
            details={"risk_reward": round(net_rr(sl, tp, ctx.spread_price), 2)},
        )


class _Track:
    """Status trade satu jalur replay (baseline atau AI)."""

    def __init__(self) -> None:
        self.active: ActiveSignalView | None = None
        self.open: ReplayTrade | None = None
        self.trades: list[ReplayTrade] = []

    def apply(self, result: Any, open_time: datetime) -> None:
        if result.exit and self.open:
            self.open.exit_time = result.exit.time
            self.open.exit_price = result.exit.price
            self.open.status = result.exit.status.value
            self.open.result_pips = result.exit.result_pips
            self.open.close_reason = result.exit.reason
            self.open = None
        self.active = result.still_active
        entry = result.new_entry
        if entry and entry.entry is not None:
            self.open = ReplayTrade(
                entry.action.value, open_time, entry.entry, entry.stop_loss,
                entry.take_profit, entry.confidence,
            )  # fmt: skip
            self.trades.append(self.open)
            self.active = ActiveSignalView(
                len(self.trades), entry.action, entry.entry, entry.stop_loss,
                entry.take_profit, open_time,
            )  # fmt: skip


async def evaluate_ai(
    session: AsyncSession,
    symbol: str,
    days: int,
    *,
    max_calls: int,
    votes: int,
    call_gap_seconds: float,
) -> dict[str, Any]:
    instrument = get_instruments()[symbol]
    cfg = get_analysis_config()
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    data = await load_dataset(session, instrument, start, end)
    m15, h1, h4 = (
        compute_indicators(data.frames[tf]) for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4)
    )
    h1_close = h1.index + Timeframe.H1.delta
    h4_close = h4.index + Timeframe.H4.delta
    spread_price = data.spread_pips * instrument.pip_size

    ai = AiGroqStrategy(
        {**cfg.strategies.get("ai_groq", {}), "votes": votes, "vote_gap_seconds": call_gap_seconds}
    )
    baseline, base_track, ai_track = SetupBaseline(), _Track(), _Track()
    setups = ai_asked = ai_accepted = 0
    budget_left = True

    for i in range(250, len(m15)):
        open_time = m15.index[i]
        if open_time < start or not candle_has_trading(
            instrument.asset_class, open_time, Timeframe.M15
        ):
            continue
        now = (open_time + Timeframe.M15.delta).to_pydatetime()
        j = int(h1_close.searchsorted(now, side="right"))
        k = int(h4_close.searchsorted(now, side="right"))
        if j < 250 or k < 250:
            continue
        window = m15.iloc[: i + 1]
        blocked = [
            r
            for r in (
                volatility_block(window, cfg.filters),
                weekend_close_block(instrument, now, cfg.filters),
            )
            if r
        ]

        h1_now, h4_now = h1.iloc[:j], h4.iloc[:k]
        base_ctx = StrategyContext(
            instrument, now, window, h1_now, h4_now, spread_price, base_track.active
        )
        base_track.apply(
            step(baseline, base_ctx, blocked, cfg.max_hold_candles, cfg.profit_close),
            open_time.to_pydatetime(),
        )

        ai_ctx = StrategyContext(
            instrument, now, window, h1_now, h4_now, spread_price, ai_track.active
        )
        ai.reset()
        if ai_track.active is None and not blocked and potential_setup(window, h1_now, h4_now):
            setups += 1
            if ai.calls + votes <= max_calls:
                ai_asked += 1
                await ai.prepare(ai_ctx)
                await asyncio.sleep(call_gap_seconds)
            else:
                budget_left = False
        result = step(ai, ai_ctx, blocked, cfg.max_hold_candles, cfg.profit_close)
        if result.new_entry:
            ai_accepted += 1
        ai_track.apply(result, open_time.to_pydatetime())
        if not budget_left and ai_track.active is None:
            end = now  # bandingkan periode yang sama dengan baseline
            break

    def metrics(trades: list[ReplayTrade]) -> dict[str, Any]:
        done = [
            t
            for t in to_trade_results(trades, instrument, data.spread_pips, data.slippage_pips)
            if t.exit_time <= end
        ]
        return compute_metrics(done).to_dict()

    return {
        "symbol": symbol,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "setups": setups,
        "ai_asked": ai_asked,
        "ai_accepted": ai_accepted,
        "ai_calls": ai.calls,
        "baseline": metrics(base_track.trades),
        "ai": metrics(ai_track.trades),
        "note": "Baseline = semua calon setup kode; AI = hanya yang disetujui AI. "
        "Biaya spread+slippage dihitung; CLOSE dini AI tidak dievaluasi.",
    }
