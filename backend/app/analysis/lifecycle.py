"""Evaluasi hasil sinyal aktif terhadap pergerakan harga.

Harga feed/grafik = BID. BUY masuk di ASK (bid + spread) dan keluar di BID; SELL masuk di
BID dan keluar di ASK. Karena itu SL/TP SELL dicek terhadap high/low + spread.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pandas as pd

from app.strategies.base import Action


class SignalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    HIT_TP = "HIT_TP"
    HIT_SL = "HIT_SL"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class PriceExit:
    status: SignalStatus
    price: float
    time: datetime


def check_price_exit(
    action: Action,
    stop_loss: float,
    take_profit: float,
    candles: pd.DataFrame,
    spread_price: float,
) -> PriceExit | None:
    """Candle pertama yang menyentuh SL/TP. Bila keduanya tersentuh di candle yang sama,
    diasumsikan SL lebih dulu (konservatif)."""
    for open_time, row in candles.iterrows():
        if action is Action.BUY:
            hit_sl = row["low"] <= stop_loss
            hit_tp = row["high"] >= take_profit
        else:
            hit_sl = row["high"] + spread_price >= stop_loss
            hit_tp = row["low"] + spread_price <= take_profit
        if hit_sl:
            return PriceExit(SignalStatus.HIT_SL, stop_loss, open_time.to_pydatetime())
        if hit_tp:
            return PriceExit(SignalStatus.HIT_TP, take_profit, open_time.to_pydatetime())
    return None


def exit_price_at_market(action: Action, bid_close: float, spread_price: float) -> float:
    return bid_close if action is Action.BUY else bid_close + spread_price


def result_pips(
    action: Action, entry: float, exit_price: float, spread_price: float, pip_size: float
) -> float:
    """Hasil bersih setelah spread. `entry` = BID saat sinyal; `exit_price` = harga keluar
    (BID untuk BUY, ASK untuk SELL)."""
    diff = exit_price - (entry + spread_price) if action is Action.BUY else entry - exit_price
    return round(diff / pip_size, 1)
