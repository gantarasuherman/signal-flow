"""Utilitas bersama untuk strategi."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

TREND_TEXT = {1: "naik", -1: "turun", 0: "datar"}


@dataclass(frozen=True)
class Trend:
    direction: int  # 1 naik, -1 turun, 0 datar
    adx: float
    strong_stack: bool  # EMA20 > EMA50 > EMA200 (atau kebalikannya)


def trend_of(df: pd.DataFrame) -> Trend:
    """Tren dari candle terakhir: harga & EMA50 di atas EMA200 = naik (kebalikannya turun)."""
    last = df.iloc[-1]
    close, fast, mid, slow = last["close"], last["ema_fast"], last["ema_mid"], last["ema_slow"]
    adx_value = float(last["adx"]) if pd.notna(last["adx"]) else 0.0
    if close > mid > slow:
        return Trend(1, adx_value, fast > mid)
    if close < mid < slow:
        return Trend(-1, adx_value, fast < mid)
    return Trend(0, adx_value, False)


def session_block(now: datetime, hours_utc: list[int] | None) -> str | None:
    """Alasan WAIT bila jam sekarang (UTC) di luar jam entry yang diizinkan."""
    if not hours_utc:
        return None
    hour = now.astimezone(UTC).hour
    if hour in hours_utc:
        return None
    return (
        f"Di luar jam trading strategi ({min(hours_utc):02d}:00–{max(hours_utc) + 1:02d}:00 UTC, "
        f"= {(min(hours_utc) + 7) % 24:02d}:00–{(max(hours_utc) + 8) % 24:02d}:00 WIB)."
    )


def take_profit_distance(
    sl_dist: float, spread: float, min_rr: float, tp_dist: float = 0.0
) -> float:
    """Jarak TP minimal agar R:R bersih setelah spread >= min_rr."""
    return max(tp_dist, min_rr * (sl_dist + spread) + spread)


def net_rr(sl_dist: float, tp_dist: float, spread: float) -> float:
    return (tp_dist - spread) / (sl_dist + spread)


def row_trend(row: pd.Series) -> int:
    """Arah tren satu baris indikator (aturan sama dengan `trend_of`, NaN → datar)."""
    close, mid, slow = row["close"], row["ema_mid"], row["ema_slow"]
    if close > mid > slow:
        return 1
    if close < mid < slow:
        return -1
    return 0
