"""Strategi `setup_trend`: masuk di calon setup searah tren (pullback ke EMA20 atau breakout
20 candle) dengan penajam yang bisa diatur (H4 searah, konfirmasi candle, tidak terlalu
jauh dari EMA50, jam sesi). Sama dengan penyaring yang dipakai AI, sehingga varian terbaiknya
bisa dipilih lewat backtest/riset sebelum dipakai."""

from pydantic import BaseModel, Field

from app.analysis.risk import price_to_pips
from app.strategies.base import Action, Decision, Strategy, StrategyContext, register
from app.strategies.common import (
    TREND_TEXT,
    net_rr,
    session_block,
    take_profit_distance,
    trend_of,
)
from app.strategies.features import SetupFilter, potential_setup


class SetupTrendParams(SetupFilter):
    sl_atr: float = Field(default=1.5, gt=0, le=10)
    rr: float = Field(default=2.0, ge=1, le=10)
    entry_hours_utc: list[int] | None = None


@register
class SetupTrendStrategy(Strategy):
    name = "setup_trend"
    Params: type[BaseModel] = SetupTrendParams
    params: SetupTrendParams

    def evaluate(self, ctx: StrategyContext) -> Decision:
        p = self.params
        if blocked := session_block(ctx.now, p.entry_hours_utc):
            return Decision(Action.WAIT, reasons=[blocked])
        setup = potential_setup(ctx.m15, ctx.h1, ctx.h4, p)
        if setup is None:
            t1, t4 = trend_of(ctx.h1).direction, trend_of(ctx.h4).direction
            return Decision(
                Action.WAIT,
                reasons=[
                    f"Tren H4 {TREND_TEXT[t4]}, H1 {TREND_TEXT[t1]}: belum ada setup yang "
                    "memenuhi semua syarat."
                ],
            )
        last = ctx.m15.iloc[-1]
        entry, atr, d = float(last["close"]), float(last["atr"]), setup.direction
        sl = p.sl_atr * atr
        tp = take_profit_distance(sl, ctx.spread_price, p.rr)
        rr = net_rr(sl, tp, ctx.spread_price)
        inst = ctx.instrument
        word = "naik" if d == 1 else "turun"
        reasons = [
            f"Tren H1 {word}" + (" dan H4 searah." if p.strict_h4 else ", H4 tidak berlawanan."),
            f"Setup M15: {setup.note}.",
        ]
        if p.confirm_candle:
            reasons.append("Candle terakhir mengonfirmasi arah.")
        reasons.append(
            f"SL {price_to_pips(sl, inst)} pip ({p.sl_atr}×ATR), TP {price_to_pips(tp, inst)} pip, "
            f"R:R 1:{rr:.1f} setelah spread."
        )
        score = 0.55 + (0.1 if p.strict_h4 else 0) + (0.1 if p.confirm_candle else 0)
        return Decision(
            Action.BUY if d == 1 else Action.SELL,
            entry=inst.round_price(entry),
            stop_loss=inst.round_price(entry - d * sl),
            take_profit=inst.round_price(entry + d * tp),
            confidence=round(min(score, 1.0), 2),
            reasons=reasons,
            details={"risk_reward": round(rr, 2), "setup": setup.kind, "atr": atr},
        )
