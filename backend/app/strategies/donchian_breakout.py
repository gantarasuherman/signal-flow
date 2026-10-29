"""Breakout Donchian searah tren H4.

- Tren: H4 naik/turun (harga & EMA50 vs EMA200), opsional H1 harus searah.
- Pemicu M15: candle PERTAMA yang ditutup di atas high tertinggi (BUY) / di bawah low
  terendah (SELL) dari `lookback` candle sebelumnya, ADX M15 >= min_adx, dan harga di sisi
  yang benar dari EMA20.
- SL = sl_atr × ATR, TP agar R:R bersih >= rr. Hanya pada jam entry_hours_utc.
"""

from typing import Any

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


class DonchianBreakoutParams(BaseModel):
    lookback: int = Field(default=20, ge=5, le=200)
    min_adx: float = Field(default=20, ge=0, le=100)
    sl_atr: float = Field(default=2.0, gt=0, le=10)
    rr: float = Field(default=2.0, ge=1, le=10)
    require_h1: bool = False
    entry_hours_utc: list[int] | None = Field(default_factory=lambda: list(range(7, 17)))


@register
class DonchianBreakoutStrategy(Strategy):
    name = "donchian_breakout"
    Params = DonchianBreakoutParams
    params: DonchianBreakoutParams

    def evaluate(self, ctx: StrategyContext) -> Decision:
        p = self.params
        m15 = ctx.m15
        last = m15.iloc[-1]
        h4, h1 = trend_of(ctx.h4), trend_of(ctx.h1)
        details: dict[str, Any] = {
            "trend_h4": TREND_TEXT[h4.direction],
            "trend_h1": TREND_TEXT[h1.direction],
        }
        if blocked := session_block(ctx.now, p.entry_hours_utc):
            return Decision(Action.WAIT, reasons=[blocked], details=details)
        if h4.direction == 0:
            return Decision(Action.WAIT, reasons=["Tren H4 belum jelas."], details=details)
        direction = h4.direction
        word = TREND_TEXT[direction]
        if p.require_h1 and h1.direction != direction:
            return Decision(
                Action.WAIT,
                reasons=[f"Tren H4 {word}, tetapi H1 {TREND_TEXT[h1.direction]}."],
                details=details,
            )

        channel = m15.iloc[-(p.lookback + 1) : -1]
        high, low = float(channel["high"].max()), float(channel["low"].min())
        close, prev_close = float(last["close"]), float(m15["close"].iloc[-2])
        adx = float(last["adx"])
        atr = float(last["atr"])
        inst = ctx.instrument
        level = high if direction == 1 else low
        details.update(channel_high=high, channel_low=low, adx_m15=round(adx, 1), atr=atr)

        broke = (
            close > high and prev_close <= high
            if direction == 1
            else close < low and prev_close >= low
        )
        side_ok = (close - float(last["ema_fast"])) * direction > 0
        if not broke:
            return Decision(
                Action.WAIT,
                reasons=[
                    f"Tren H4 {word}. Menunggu candle M15 ditutup "
                    f"{'di atas' if direction == 1 else 'di bawah'} {inst.round_price(level)} "
                    f"({'high' if direction == 1 else 'low'} {p.lookback} candle)."
                ],
                details=details,
            )
        if adx < p.min_adx or not side_ok:
            return Decision(
                Action.WAIT,
                reasons=[f"Breakout terjadi tetapi momentum lemah (ADX M15 {adx:.0f})."],
                details=details,
            )

        sl_dist = p.sl_atr * atr
        tp_dist = take_profit_distance(sl_dist, ctx.spread_price, p.rr)
        rr = net_rr(sl_dist, tp_dist, ctx.spread_price)
        reasons = [
            f"Tren H4 {word} (ADX {h4.adx:.0f}).",
            f"Candle M15 ditutup {'di atas high' if direction == 1 else 'di bawah low'} "
            f"{p.lookback} candle terakhir ({inst.round_price(level)}), ADX M15 {adx:.0f}.",
            f"SL {price_to_pips(sl_dist, inst)} pip ({p.sl_atr}×ATR), "
            f"TP {price_to_pips(tp_dist, inst)} pip, R:R 1:{rr:.1f} setelah spread.",
        ]
        score = 0.5 + (0.15 if h1.direction == direction else 0) + (0.1 if adx >= 30 else 0)
        score += 0.1 if h4.adx >= 25 else 0
        details.update(risk_reward=round(rr, 2))
        return Decision(
            Action.BUY if direction == 1 else Action.SELL,
            entry=inst.round_price(close),
            stop_loss=inst.round_price(close - direction * sl_dist),
            take_profit=inst.round_price(close + direction * tp_dist),
            confidence=round(min(score, 1.0), 2),
            reasons=reasons,
            details=details,
        )
