"""Strategi tren + pullback multi-timeframe.

- Tren: H1 dan H4 harus searah (harga & EMA50 di atas EMA200 untuk naik, kebalikannya
  untuk turun) dengan ADX cukup kuat.
- Pemicu M15 (BUY): harga pullback ke EMA20 lalu ditutup kembali di atasnya, ditambah
  RSI keluar dari zona jenuh jual dan/atau MACD cross naik. SELL kebalikannya.
- SL = sl_atr × ATR; TP = tp_atr × ATR, dilebarkan bila perlu agar R:R setelah spread
  tetap >= min_rr.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.analysis.risk import price_to_pips
from app.strategies.base import (
    Action,
    ActiveSignalView,
    Decision,
    Strategy,
    StrategyContext,
    register,
)
from app.strategies.common import (
    TREND_TEXT,
    Trend,
    net_rr,
    session_block,
    take_profit_distance,
    trend_of,
)

__all__ = ["TREND_TEXT", "Trend", "TrendPullbackParams", "TrendPullbackStrategy", "trend_of"]


class TrendPullbackParams(BaseModel):
    min_adx: float = Field(default=20, ge=0, le=100)
    strong_adx: float = Field(default=25, ge=0, le=100)
    pullback_lookback: int = Field(default=5, ge=1, le=20)
    pullback_atr: float = Field(default=0.25, ge=0, le=2, description="Toleransi sentuh EMA20")
    trigger_lookback: int = Field(default=3, ge=1, le=10)
    rsi_buy_level: float = Field(default=40, ge=10, le=50)
    rsi_sell_level: float = Field(default=60, ge=50, le=90)
    rsi_overbought: float = Field(default=70, ge=50, le=95)
    rsi_oversold: float = Field(default=30, ge=5, le=50)
    min_triggers: int = Field(default=2, ge=1, le=3)
    sl_atr: float = Field(default=1.5, gt=0, le=10)
    tp_atr: float = Field(default=3.0, gt=0, le=20)
    min_rr: float = Field(default=2.0, ge=1, le=10)
    min_bars_before_close: int = Field(default=2, ge=0, le=50)
    early_close: bool = Field(
        default=True, description="CLOSE dini saat momentum melemah / tren H1 berbalik"
    )
    trend_mode: Literal["h1_h4", "h4"] = Field(
        default="h1_h4", description="h1_h4 = H1 & H4 harus searah; h4 = cukup H4"
    )
    entry_hours_utc: list[int] | None = Field(
        default=None, description="Jam (UTC) yang boleh entry, mis. 7..16 = London & New York"
    )


def _crossed(prev_a: float, prev_b: float, a: float, b: float, direction: int) -> bool:
    if direction == 1:
        return prev_a <= prev_b and a > b
    return prev_a >= prev_b and a < b


@register
class TrendPullbackStrategy(Strategy):
    name = "trend_pullback"
    Params = TrendPullbackParams
    params: TrendPullbackParams

    def evaluate(self, ctx: StrategyContext) -> Decision:
        p = self.params
        h1, h4 = trend_of(ctx.h1), trend_of(ctx.h4)
        m15 = ctx.m15
        last = m15.iloc[-1]
        details: dict[str, Any] = {
            "trend_h1": TREND_TEXT[h1.direction],
            "trend_h4": TREND_TEXT[h4.direction],
            "adx_h1": round(h1.adx, 1),
            "adx_h4": round(h4.adx, 1),
        }
        trend_line = f"Tren H4 {TREND_TEXT[h4.direction]}, H1 {TREND_TEXT[h1.direction]}"

        if blocked := session_block(ctx.now, p.entry_hours_utc):
            return Decision(Action.WAIT, reasons=[trend_line + ".", blocked], details=details)
        if p.trend_mode == "h4":
            if h4.direction == 0:
                return Decision(
                    Action.WAIT,
                    reasons=[f"{trend_line} — tren H4 belum jelas."],
                    details=details,
                )
            direction = h4.direction
            adx_ok = h4.adx >= p.min_adx
        else:
            if h1.direction == 0 or h4.direction == 0 or h1.direction != h4.direction:
                return Decision(
                    Action.WAIT,
                    reasons=[f"{trend_line} — belum searah, tunggu tren yang jelas."],
                    details=details,
                )
            direction = h1.direction
            adx_ok = max(h1.adx, h4.adx) >= p.min_adx
        if not adx_ok:
            return Decision(
                Action.WAIT,
                reasons=[
                    f"{trend_line}, tetapi tren lemah (ADX H1 {h1.adx:.0f}, H4 {h4.adx:.0f} "
                    f"< {p.min_adx:.0f})."
                ],
                details=details,
            )

        atr = float(last["atr"])
        window = m15.iloc[-p.pullback_lookback :]
        if direction == 1:
            touched = (window["low"] <= window["ema_fast"] + p.pullback_atr * window["atr"]).any()
            reclaimed = last["close"] > last["ema_fast"] and last["close"] > last["ema_mid"]
        else:
            touched = (window["high"] >= window["ema_fast"] - p.pullback_atr * window["atr"]).any()
            reclaimed = last["close"] < last["ema_fast"] and last["close"] < last["ema_mid"]
        pullback = bool(touched and reclaimed)

        recent = m15.iloc[-(p.trigger_lookback + 1) :]
        rsi_level = p.rsi_buy_level if direction == 1 else p.rsi_sell_level
        rsi_exit = any(
            _crossed(a, rsi_level, b, rsi_level, direction)
            for a, b in zip(recent["rsi"].iloc[:-1], recent["rsi"].iloc[1:], strict=True)
        )
        macd_cross = any(
            _crossed(pm, ps, m, s, direction)
            for pm, ps, m, s in zip(
                recent["macd"].iloc[:-1],
                recent["macd_signal"].iloc[:-1],
                recent["macd"].iloc[1:],
                recent["macd_signal"].iloc[1:],
                strict=True,
            )
        )
        rsi_now = float(last["rsi"])
        details.update(
            rsi=round(rsi_now, 1),
            macd_hist=float(last["macd_hist"]),
            atr=atr,
            pullback=pullback,
            rsi_exit=rsi_exit,
            macd_cross=macd_cross,
        )

        word = "naik" if direction == 1 else "turun"
        reasons = [
            f"Tren H4 {word} (ADX {h4.adx:.0f})."
            if p.trend_mode == "h4"
            else f"Tren H4 dan H1 sama-sama {word} (ADX H1 {h1.adx:.0f}, H4 {h4.adx:.0f})."
        ]
        if pullback:
            side = "atas" if direction == 1 else "bawah"
            reasons.append(f"Harga sempat pullback ke EMA20 lalu ditutup kembali di {side}nya.")
        if rsi_exit:
            zone = "jenuh jual" if direction == 1 else "jenuh beli"
            reasons.append(
                f"RSI keluar dari zona {zone} (melewati {rsi_level:.0f}), kini {rsi_now:.0f}."
            )
        if macd_cross:
            reasons.append(f"MACD memotong garis sinyal ke arah {word}.")

        triggers = sum((pullback, rsi_exit, macd_cross))
        if not pullback or triggers < p.min_triggers:
            missing = []
            if not pullback:
                missing.append("pullback ke EMA20")
            if not rsi_exit:
                missing.append("RSI keluar zona")
            if not macd_cross:
                missing.append("MACD cross")
            return Decision(
                Action.WAIT,
                reasons=[*reasons[:1], f"Menunggu pemicu M15: {', '.join(missing)}."],
                details=details,
            )
        if direction == 1 and rsi_now >= p.rsi_overbought:
            return Decision(
                Action.WAIT,
                reasons=[
                    *reasons,
                    f"Namun RSI {rsi_now:.0f} sudah jenuh beli, rawan terlambat masuk.",
                ],
                details=details,
            )
        if direction == -1 and rsi_now <= p.rsi_oversold:
            return Decision(
                Action.WAIT,
                reasons=[
                    *reasons,
                    f"Namun RSI {rsi_now:.0f} sudah jenuh jual, rawan terlambat masuk.",
                ],
                details=details,
            )

        entry = float(last["close"])
        sl_dist = p.sl_atr * atr
        tp_dist = take_profit_distance(sl_dist, ctx.spread_price, p.min_rr, p.tp_atr * atr)
        stop_loss = entry - direction * sl_dist
        take_profit = entry + direction * tp_dist
        rr = net_rr(sl_dist, tp_dist, ctx.spread_price)
        inst = ctx.instrument
        reasons.append(
            f"SL {price_to_pips(sl_dist, inst)} pip ({p.sl_atr}×ATR), "
            f"TP {price_to_pips(tp_dist, inst)} pip, R:R 1:{rr:.1f} setelah spread."
        )

        score = 0.45
        score += 0.15 if triggers == 3 else 0.0
        score += 0.1 if h4.adx >= p.strong_adx else 0.0
        score += 0.1 if h1.adx >= p.strong_adx else 0.0
        score += 0.1 if h1.strong_stack and h4.strong_stack else 0.0
        candle_agrees = (last["close"] - last["open"]) * direction > 0
        score += 0.05 if candle_agrees else 0.0
        score += 0.05 if 40 <= rsi_now <= 60 else 0.0
        details.update(risk_reward=round(rr, 2), triggers=triggers)

        return Decision(
            Action.BUY if direction == 1 else Action.SELL,
            entry=inst.round_price(entry),
            stop_loss=inst.round_price(stop_loss),
            take_profit=inst.round_price(take_profit),
            confidence=round(min(score, 1.0), 2),
            reasons=reasons,
            details=details,
        )

    def should_close(self, ctx: StrategyContext, active: ActiveSignalView) -> str | None:
        p = self.params
        if not p.early_close:
            return None
        bars_since = int((ctx.m15.index > active.candle_time).sum())
        if bars_since < p.min_bars_before_close:
            return None
        direction = 1 if active.action is Action.BUY else -1

        h1 = trend_of(ctx.h1)
        if h1.direction == -direction:
            return f"Tren H1 berbalik menjadi {TREND_TEXT[h1.direction]}."

        last2 = ctx.m15.iloc[-2:]
        hist_against = ((last2["macd_hist"] * direction) < 0).all()
        close_vs_ema = (last2["close"].iloc[-1] - last2["ema_fast"].iloc[-1]) * direction < 0
        if hist_against and close_vs_ema:
            side = "bawah" if direction == 1 else "atas"
            return f"Momentum melemah: histogram MACD berbalik dan harga ditutup di {side} EMA20."
        return None
