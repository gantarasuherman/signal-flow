"""Fakta pasar yang dihitung kode (bukan dibaca LLM dari deretan angka) + penyaring calon
setup. Dipakai strategi AI agar LLM menilai fakta yang sudah benar, dan agar LLM hanya
dipanggil saat memang ada kandidat setup."""

from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.strategies.common import TREND_TEXT, trend_of
from app.strategies.patterns import describe, detect_patterns, pattern_bias

SWING_LOOKBACK = 20
PULLBACK_LOOKBACK = 6
PULLBACK_ATR = 0.5


def _ema_order(row: pd.Series) -> str:
    items = {
        "harga": row["close"],
        "EMA20": row["ema_fast"],
        "EMA50": row["ema_mid"],
        "EMA200": row["ema_slow"],
    }
    return " > ".join(name for name, _ in sorted(items.items(), key=lambda kv: -kv[1]))


def _rsi_zone(rsi: float) -> str:
    if rsi >= 70:
        return "jenuh beli"
    if rsi >= 55:
        return "kuat"
    if rsi > 45:
        return "netral"
    if rsi > 30:
        return "lemah"
    return "jenuh jual"


def _adx_text(adx: float) -> str:
    return "kuat" if adx >= 25 else "sedang" if adx >= 20 else "lemah"


def _macd_text(df: pd.DataFrame, lookback: int = 5) -> str:
    hist = df["macd_hist"].tail(lookback + 1)
    sign = "positif" if hist.iloc[-1] > 0 else "negatif"
    rising = hist.iloc[-1] > hist.iloc[-2]
    for i in range(len(hist) - 1, 0, -1):
        if (hist.iloc[i] > 0) != (hist.iloc[i - 1] > 0):
            bars = len(hist) - 1 - i
            arah = "naik" if hist.iloc[i] > 0 else "turun"
            return f"histogram {sign}, cross {arah} {bars} candle lalu"
    return f"histogram {sign}, {'menguat' if rising else 'melemah'}"


def timeframe_facts(df: pd.DataFrame, digits: int) -> dict[str, str]:
    last = df.iloc[-1]
    atr = float(last["atr"])
    recent = df.tail(SWING_LOOKBACK)
    swing_high, swing_low = float(recent["high"].max()), float(recent["low"].min())
    close = float(last["close"])
    width = float(last["bb_upper"] - last["bb_lower"]) or 1e-12
    bb_pos = (close - float(last["bb_lower"])) / width * 100
    body = float(last["close"] - last["open"])
    candle = "bullish" if body > 0 else "bearish" if body < 0 else "doji"
    return {
        "tren": TREND_TEXT[trend_of(df).direction],
        "urutan": _ema_order(last),
        "rsi": f"{float(last['rsi']):.0f} ({_rsi_zone(float(last['rsi']))})",
        "macd": _macd_text(df),
        "adx": f"{float(last['adx']):.0f} ({_adx_text(float(last['adx']))})",
        "bollinger": f"posisi {bb_pos:.0f}% dari bawah ke atas",
        "swing": (
            f"high {swing_high:.{digits}f} ({(swing_high - close) / atr:.1f} ATR di atas), "
            f"low {swing_low:.{digits}f} ({(close - swing_low) / atr:.1f} ATR di bawah)"
        ),
        "candle_terakhir": f"{candle}, badan {abs(body) / atr:.1f} ATR",
        "pola": describe(detect_patterns(df, atr)),
    }


@dataclass(frozen=True)
class Setup:
    direction: int  # 1 BUY, -1 SELL
    kind: str  # "pullback" / "breakout"
    note: str


class SetupFilter(BaseModel):
    """Penajam calon setup (dipilih lewat backtest, lihat strategi setup_trend)."""

    strict_h4: bool = Field(
        default=False, description="H4 wajib searah (bukan sekadar tidak berlawanan)"
    )
    confirm_candle: bool = Field(
        default=False, description="Candle M15 terakhir searah & ditutup melewati close sebelumnya"
    )
    max_extension_atr: float | None = Field(
        default=None, gt=0, description="Jarak maks harga ke EMA50 M15 (× ATR); hindari masuk telat"
    )
    pattern_confirm: bool = Field(
        default=False,
        description="Wajib pola candlestick searah, tanpa pola lawan / Spinning Top",
    )
    kinds: list[Literal["pullback", "breakout"]] = Field(
        default_factory=lambda: ["pullback", "breakout"]
    )


def potential_setup(
    m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame, flt: SetupFilter | None = None
) -> Setup | None:
    """Calon setup searah tren: H1 bertren dan H4 tidak berlawanan, lalu di M15 ada pullback
    ke EMA20 yang ditutup kembali searah tren, atau breakout high/low 20 candle.
    `flt` menambah syarat penajam (H4 searah, konfirmasi candle, tidak terlalu jauh)."""
    flt = flt or SetupFilter()
    t1, t4 = trend_of(h1).direction, trend_of(h4).direction
    if t1 == 0 or t4 == -t1 or (flt.strict_h4 and t4 != t1):
        return None
    d = t1
    last, prev = m15.iloc[-1], m15.iloc[-2]
    close, ema20, atr = float(last["close"]), float(last["ema_fast"]), float(last["atr"])
    rsi = float(last["rsi"])
    if (d == 1 and rsi >= 70) or (d == -1 and rsi <= 30):
        return None  # sudah jenuh, rawan terlambat
    if flt.max_extension_atr and abs(close - float(last["ema_mid"])) > flt.max_extension_atr * atr:
        return None  # harga sudah lari jauh dari EMA50
    if flt.confirm_candle and not (
        (close - float(last["open"])) * d > 0 and (close - float(prev["close"])) * d > 0
    ):
        return None  # candle terakhir belum mengonfirmasi arah
    patterns = detect_patterns(m15, atr)
    if flt.pattern_confirm and pattern_bias(patterns) != d:
        return None  # tidak ada pola searah (atau ada pola lawan / ragu-ragu)
    names = ", ".join(p.name for p in patterns)
    pattern_note = f", pola {names}" if names else ""

    window = m15.tail(PULLBACK_LOOKBACK)
    if d == 1:
        touched = (window["low"] <= window["ema_fast"] + PULLBACK_ATR * window["atr"]).any()
        reclaimed = close > ema20
    else:
        touched = (window["high"] >= window["ema_fast"] - PULLBACK_ATR * window["atr"]).any()
        reclaimed = close < ema20
    if "pullback" in flt.kinds and touched and reclaimed:
        note = "pullback ke EMA20 lalu ditutup kembali searah tren"
        return Setup(d, "pullback", note + pattern_note)

    channel = m15.iloc[-(SWING_LOOKBACK + 1) : -1]
    if "breakout" in flt.kinds:
        if d == 1 and close > float(channel["high"].max()):
            return Setup(d, "breakout", "breakout di atas high 20 candle" + pattern_note)
        if d == -1 and close < float(channel["low"].min()):
            return Setup(d, "breakout", "breakout di bawah low 20 candle" + pattern_note)
    return None
