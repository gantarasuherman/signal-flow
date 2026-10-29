"""Breakout rentang sesi Asia saat sesi London/New York.

- Rentang: high/low candle M15 antara range_start_utc dan range_end_utc (bawaan 00–07 UTC
  = 07:00–14:00 WIB).
- Entry: candle M15 PERTAMA yang ditutup di luar rentang (+ buffer) antara range_end_utc dan
  trade_until_utc. Maksimal satu sinyal per hari; bila rentang sudah ditembus ke arah mana
  pun sebelumnya, hari itu dilewati.
- Filter tren (opsional): arah breakout harus searah tren H4.
- SL: di tengah rentang (atau sl_atr × ATR), dibatasi min/max × ATR. TP: R:R bersih >= rr.
"""

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.analysis.risk import price_to_pips
from app.core.timeframes import Timeframe
from app.strategies.base import Action, Decision, Strategy, StrategyContext, register
from app.strategies.common import TREND_TEXT, net_rr, take_profit_distance, trend_of

WIB_OFFSET = 7


class SessionBreakoutParams(BaseModel):
    range_start_utc: int = Field(default=0, ge=0, le=23)
    range_end_utc: int = Field(default=7, ge=1, le=23)
    trade_until_utc: int = Field(default=12, ge=1, le=24)
    buffer_atr: float = Field(default=0.1, ge=0, le=2)
    min_range_atr: float = Field(default=1.0, ge=0, le=20)
    max_range_atr: float = Field(default=8.0, gt=0, le=50)
    sl_mode: Literal["mid_range", "atr"] = "mid_range"
    sl_atr: float = Field(default=1.5, gt=0, le=10)
    min_sl_atr: float = Field(default=0.75, gt=0, le=10)
    max_sl_atr: float = Field(default=3.0, gt=0, le=20)
    rr: float = Field(default=2.0, ge=1, le=10)
    trend_filter: Literal["h4", "none"] = "h4"


def _wib(hour_utc: int) -> str:
    return f"{(hour_utc + WIB_OFFSET) % 24:02d}:00"


@register
class SessionBreakoutStrategy(Strategy):
    name = "session_breakout"
    Params = SessionBreakoutParams
    params: SessionBreakoutParams

    def evaluate(self, ctx: StrategyContext) -> Decision:
        p = self.params
        m15 = ctx.m15
        last = m15.iloc[-1]
        last_open: pd.Timestamp = m15.index[-1]
        details: dict[str, Any] = {}

        if not p.range_end_utc <= last_open.hour < p.trade_until_utc:
            return Decision(
                Action.WAIT,
                reasons=[
                    f"Strategi breakout sesi Asia hanya aktif {_wib(p.range_end_utc)}–"
                    f"{_wib(p.trade_until_utc)} WIB; rentang dibentuk {_wib(p.range_start_utc)}–"
                    f"{_wib(p.range_end_utc)} WIB."
                ],
                details=details,
            )

        day = m15.tail(int(24 * 60 / Timeframe.M15.minutes) + 4)
        day = day[day.index >= last_open.normalize()]
        hours = day.index.hour
        rng = day[(hours >= p.range_start_utc) & (hours < p.range_end_utc)]
        expected = (p.range_end_utc - p.range_start_utc) * 4
        if len(rng) < expected * 0.6:
            return Decision(
                Action.WAIT,
                reasons=["Data rentang sesi Asia hari ini belum lengkap."],
                details=details,
            )

        high, low = float(rng["high"].max()), float(rng["low"].min())
        atr = float(last["atr"])
        width = high - low
        inst = ctx.instrument
        details.update(range_high=high, range_low=low, range_atr=round(width / atr, 2), atr=atr)
        range_text = (
            f"Rentang Asia {inst.round_price(low)}–{inst.round_price(high)} "
            f"({price_to_pips(width, inst)} pip)"
        )
        if width < p.min_range_atr * atr or width > p.max_range_atr * atr:
            size = "sempit" if width < p.min_range_atr * atr else "lebar"
            return Decision(Action.WAIT, reasons=[f"{range_text} terlalu {size}."], details=details)

        buf = p.buffer_atr * atr
        up, down = high + buf, low - buf
        after = day[hours >= p.range_end_utc]
        prev = after["close"].iloc[:-1]
        untouched = bool(((prev <= up) & (prev >= down)).all())
        close = float(last["close"])
        if close > up and untouched:
            direction = 1
        elif close < down and untouched:
            direction = -1
        else:
            note = "menunggu breakout" if untouched else "sudah ditembus lebih awal hari ini"
            return Decision(Action.WAIT, reasons=[f"{range_text}: {note}."], details=details)

        word = "atas" if direction == 1 else "bawah"
        reasons = [f"{range_text} ditembus ke {word} saat sesi London/New York."]
        h4 = trend_of(ctx.h4)
        details["trend_h4"] = TREND_TEXT[h4.direction]
        if p.trend_filter == "h4":
            if h4.direction != direction:
                return Decision(
                    Action.WAIT,
                    reasons=[
                        *reasons,
                        f"Namun tren H4 {TREND_TEXT[h4.direction]}, breakout diabaikan.",
                    ],
                    details=details,
                )
            reasons.append(f"Searah tren H4 ({TREND_TEXT[h4.direction]}).")

        raw_sl = abs(close - (high + low) / 2) if p.sl_mode == "mid_range" else p.sl_atr * atr
        sl_dist = min(max(raw_sl, p.min_sl_atr * atr), p.max_sl_atr * atr)
        tp_dist = take_profit_distance(sl_dist, ctx.spread_price, p.rr)
        rr = net_rr(sl_dist, tp_dist, ctx.spread_price)
        reasons.append(
            f"SL {price_to_pips(sl_dist, inst)} pip, TP {price_to_pips(tp_dist, inst)} pip, "
            f"R:R 1:{rr:.1f} setelah spread."
        )

        score = 0.55
        score += 0.15 if h4.direction == direction else 0.0
        score += 0.1 if 1.5 <= width / atr <= 5 else 0.0
        score += 0.05 if (close - float(last["open"])) * direction > 0 else 0.0
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
