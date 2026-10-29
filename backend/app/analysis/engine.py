"""Satu langkah keputusan sinyal (murni, tanpa I/O) — dipakai worker live dan backtest."""

from dataclasses import dataclass, replace
from datetime import datetime

from app.analysis.lifecycle import (
    SignalStatus,
    TrailingStopConfig,
    check_price_exit,
    exit_price_at_market,
    result_pips,
)
from app.analysis.profit_lock import ProfitCloseConfig, profit_lock_reason
from app.core.timeframes import duration_text
from app.strategies.base import (
    Action,
    ActiveSignalView,
    Decision,
    Strategy,
    StrategyContext,
)


@dataclass(frozen=True)
class ExitEvent:
    status: SignalStatus
    price: float
    time: datetime
    reason: str
    result_pips: float


@dataclass
class StepResult:
    decision: Decision
    exit: ExitEvent | None
    new_entry: Decision | None
    still_active: ActiveSignalView | None
    blocked: list[str]


def _exit(
    active: ActiveSignalView,
    status: SignalStatus,
    price: float,
    time: datetime,
    reason: str,
    ctx: StrategyContext,
) -> ExitEvent:
    pips = result_pips(
        active.action, active.entry, price, ctx.spread_price, ctx.instrument.pip_size
    )
    return ExitEvent(status, price, time, reason, pips)


def step(
    strategy: Strategy,
    ctx: StrategyContext,
    blocked: list[str],
    max_hold_candles: int,
    profit_close: ProfitCloseConfig | None = None,
    trailing: TrailingStopConfig | None = None,
) -> StepResult:
    active = ctx.active
    last_time = ctx.m15.index[-1].to_pydatetime()
    exit_event: ExitEvent | None = None
    bars_since = 0

    # 1) Sinyal aktif kena SL/TP pada candle setelah sinyal muncul?
    if active:
        after = ctx.m15[ctx.m15.index > active.candle_time]
        bars_since = len(after)
        hit = check_price_exit(
            active.action,
            active.stop_loss,
            active.take_profit,
            after,
            ctx.spread_price,
            entry=active.entry,
            trailing=trailing,
        )
        if hit:
            if hit.trailing:
                reason = "Trailing stop tersentuh: keuntungan terbaik dikunci."
            elif hit.status is SignalStatus.HIT_TP:
                reason = "Take profit tercapai."
            else:
                reason = "Stop loss tersentuh."
            exit_event = _exit(active, hit.status, hit.price, hit.time, reason, ctx)
            active = None

    ctx = replace(ctx, active=active)

    # 2) Keputusan strategi + filter
    decision = strategy.evaluate(ctx)
    if decision.is_entry and blocked:
        decision = Decision(
            Action.WAIT,
            reasons=[
                *decision.reasons[:1],
                f"Sinyal {decision.action} ditahan: {' '.join(blocked)}",
            ],
            details=decision.details,
        )

    # 3) CLOSE dini untuk sinyal yang masih aktif
    if active:
        reason: str | None = None
        if decision.is_entry and decision.action != active.action:
            reason = f"Sinyal berbalik arah menjadi {decision.action}."
        else:
            reason = strategy.should_close(ctx, active)
        if reason is None:
            reason = profit_lock_reason(ctx, active, profit_close)
        if reason is None and bars_since >= max_hold_candles:
            limit = duration_text(max_hold_candles * ctx.timeframe.minutes)
            reason = f"Batas waktu sinyal ({limit}) tercapai."
        if reason:
            price = exit_price_at_market(
                active.action, float(ctx.m15["close"].iloc[-1]), ctx.spread_price
            )
            exit_event = _exit(active, SignalStatus.CLOSED, price, last_time, reason, ctx)
            active = None

    new_entry = decision if active is None and decision.is_entry else None
    return StepResult(decision, exit_event, new_entry, active, blocked)
