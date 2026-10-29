"""Strategi `candle_pattern`: masuk saat pola candlestick pembalikan/lanjutan (Hammer,
Morning Star, Engulfing, Piercing Line, Three White Soldiers, dan kebalikannya) muncul di
area support/resistance M15. Tren H1 bisa dijadikan syarat. SL di luar ujung pola."""

from typing import Literal

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
from app.strategies.patterns import PATTERN_INFO, read_patterns


class CandlePatternParams(BaseModel):
    trend_filter: Literal["h1", "h1_h4", "none"] = Field(
        default="h1", description="Pola wajib searah tren H1 (/+H4 tidak berlawanan) atau bebas"
    )
    require_level: bool = Field(default=True, description="Pola wajib di area support/resistance")
    min_strength: int = Field(default=2, ge=1, le=3)
    patterns: list[str] | None = Field(
        default=None, description="Hanya pola tertentu (nama di PATTERN_INFO); null = semua"
    )
    sl_buffer_atr: float = Field(default=0.2, ge=0, le=2)
    min_sl_atr: float = Field(default=0.5, gt=0, le=5)
    max_sl_atr: float = Field(default=3.0, gt=0, le=10)
    rr: float = Field(default=2.0, ge=1, le=10)
    entry_hours_utc: list[int] | None = None


@register
class CandlePatternStrategy(Strategy):
    name = "candle_pattern"
    Params: type[BaseModel] = CandlePatternParams
    params: CandlePatternParams

    def evaluate(self, ctx: StrategyContext) -> Decision:
        p = self.params
        if blocked := session_block(ctx.now, p.entry_hours_utc):
            return Decision(Action.WAIT, reasons=[blocked])
        t1, t4 = trend_of(ctx.h1).direction, trend_of(ctx.h4).direction
        trend = t1 if p.trend_filter != "none" else trend_of(ctx.m15).direction
        reads = [
            r
            for r in read_patterns(ctx.m15.tail(60), trend)
            if r.pattern.bias and (p.patterns is None or r.pattern.name in p.patterns)
        ]
        if not reads:
            return Decision(
                Action.WAIT, reasons=["Belum ada pola candlestick searah di candle M15 terakhir."]
            )
        if len({r.pattern.bias for r in reads}) > 1:
            names = ", ".join(r.pattern.name for r in reads)
            return Decision(Action.WAIT, reasons=[f"Pola saling bertentangan ({names})."])
        best = max(reads, key=lambda r: r.strength)
        d = best.pattern.bias
        word = "naik" if d == 1 else "turun"
        if p.trend_filter != "none" and t1 != d:
            return Decision(
                Action.WAIT,
                reasons=[
                    f"{best.pattern.name} ({word}) muncul, tapi tren H1 {TREND_TEXT[t1]}: "
                    "tidak dipakai melawan tren."
                ],
            )
        if p.trend_filter == "h1_h4" and t4 == -d:
            return Decision(
                Action.WAIT, reasons=[f"{best.pattern.name} searah H1, tapi H4 berlawanan."]
            )
        if p.require_level and not best.at_level:
            return Decision(
                Action.WAIT,
                reasons=[f"{best.pattern.name} muncul bukan di area support/resistance."],
            )
        if best.strength < p.min_strength:
            return Decision(
                Action.WAIT,
                reasons=[f"{best.pattern.name} masih {best.strength_text} ({best.note})."],
            )

        last = ctx.m15.iloc[-1]
        entry, atr = float(last["close"]), float(last["atr"])
        span = ctx.m15.iloc[-3:]
        extreme = float(span["low"].min()) if d == 1 else float(span["high"].max())
        sl = max(abs(entry - extreme) + p.sl_buffer_atr * atr, p.min_sl_atr * atr)
        if sl > p.max_sl_atr * atr:
            return Decision(
                Action.WAIT,
                reasons=[f"{best.pattern.name} terlalu panjang: SL > {p.max_sl_atr}×ATR."],
            )
        tp = take_profit_distance(sl, ctx.spread_price, p.rr)
        rr = net_rr(sl, tp, ctx.spread_price)
        inst = ctx.instrument
        reasons = [
            f"Pola {best.pattern.name}: {PATTERN_INFO[best.pattern.name][1]}.",
            f"Kekuatan {best.strength_text}: {best.note}.",
        ]
        if p.trend_filter != "none":
            reasons.append(f"Tren H1 {word}, H4 {TREND_TEXT[t4]}.")
        reasons.append(
            f"SL di luar ujung pola ({price_to_pips(sl, inst)} pip), TP "
            f"{price_to_pips(tp, inst)} pip, R:R 1:{rr:.1f} setelah spread."
        )
        return Decision(
            Action.BUY if d == 1 else Action.SELL,
            entry=inst.round_price(entry),
            stop_loss=inst.round_price(entry - d * sl),
            take_profit=inst.round_price(entry + d * tp),
            confidence=round(0.45 + 0.1 * best.strength, 2),
            reasons=reasons,
            details={"risk_reward": round(rr, 2), "pattern": best.pattern.name, "atr": atr},
        )
