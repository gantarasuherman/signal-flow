"""Evaluasi hasil sinyal aktif terhadap pergerakan harga.

Harga feed/grafik = BID. BUY masuk di ASK (bid + spread) dan keluar di BID; SELL masuk di
BID dan keluar di ASK. Karena itu SL/TP SELL dicek terhadap high/low + spread.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, Field

from app.strategies.base import Action


class SignalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    HIT_TP = "HIT_TP"
    HIT_SL = "HIT_SL"
    CLOSED = "CLOSED"


class TrailingStopConfig(BaseModel):
    """Trailing stop: setelah untung >= activate_r, stop mengikuti harga terbaik sejak entry
    sejauh distance_r (R = jarak SL awal). activate_r = distance_r → stop pertama di entry."""

    enabled: bool = False
    activate_r: float = Field(default=1.0, gt=0, le=20)
    distance_r: float = Field(default=1.0, gt=0, le=20)
    # false = TP dilepas, posisi hanya ditutup oleh trailing stop / SL / sinyal lain
    take_profit: bool = True


@dataclass(frozen=True)
class PriceExit:
    status: SignalStatus
    price: float
    time: datetime
    trailing: bool = False


def _exit_side(row: pd.Series, d: int, spread_price: float) -> tuple[float, float]:
    """(harga terburuk, harga terbaik) candle di sisi keluar: BUY = BID, SELL = ASK."""
    if d == 1:
        return row["low"], row["high"]
    return row["high"] + spread_price, row["low"] + spread_price


def trailing_stops(
    action: Action,
    stop_loss: float,
    entry: float,
    candles: pd.DataFrame,
    spread_price: float,
    trailing: TrailingStopConfig,
) -> list[float]:
    """Stop yang berlaku di tiap candle (len = candle + 1; elemen terakhir = stop saat ini).
    Stop candle ke-i hanya memakai harga terbaik candle SEBELUMNYA (urutan high/low di dalam
    candle tidak diketahui). Untung diukur dari harga yang dibayar: BUY di ASK, SELL di BID."""
    d = 1 if action is Action.BUY else -1
    risk = abs(entry - stop_loss)
    paid = entry + spread_price if d == 1 else entry
    stop, best = stop_loss, None
    stops = [stop]
    for _, row in candles.iterrows():
        favorable = _exit_side(row, d, spread_price)[1]
        best = favorable if best is None else (max if d == 1 else min)(best, favorable)
        if risk and (best - paid) * d >= trailing.activate_r * risk:
            candidate = best - d * trailing.distance_r * risk
            if (candidate - stop) * d > 0:
                stop = candidate
        stops.append(stop)
    return stops


def check_price_exit(
    action: Action,
    stop_loss: float,
    take_profit: float,
    candles: pd.DataFrame,
    spread_price: float,
    entry: float | None = None,
    trailing: TrailingStopConfig | None = None,
) -> PriceExit | None:
    """Candle pertama yang menyentuh SL/TP. Bila keduanya tersentuh di candle yang sama,
    diasumsikan SL lebih dulu (konservatif). Dengan trailing stop (butuh `entry`) SL
    bergerak mengikuti `trailing_stops`."""
    trail = trailing if trailing and trailing.enabled and entry is not None else None
    use_tp = trail is None or trail.take_profit
    d = 1 if action is Action.BUY else -1
    stops = (
        trailing_stops(action, stop_loss, entry, candles, spread_price, trail)
        if trail and entry is not None
        else [stop_loss] * (len(candles) + 1)
    )
    for i, (open_time, row) in enumerate(candles.iterrows()):
        adverse, favorable = _exit_side(row, d, spread_price)
        stop = stops[i]
        if (adverse - stop) * d <= 0:
            moved = stop != stop_loss
            status = SignalStatus.CLOSED if moved else SignalStatus.HIT_SL
            return PriceExit(status, stop, open_time.to_pydatetime(), trailing=moved)
        if use_tp and (favorable - take_profit) * d >= 0:
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
