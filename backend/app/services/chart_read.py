"""Ringkasan kondisi chart dalam bahasa sehari-hari (tren, momentum, level penting).

Bukan sinyal strategi teruji: dipakai untuk menjelaskan apa yang terlihat di grafik, termasuk
saat strategi menunggu atau dinonaktifkan. Aturan tren sama dengan strategi (`trend_of`)."""

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.analysis.risk import price_to_pips
from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.strategies.common import trend_of

Tone = Literal["up", "down", "neutral", "warn"]
LEVEL_LOOKBACK = 50  # candle frame entry untuk mencari support/resistance terdekat
MIN_BARS = 60
# Bobot tren: timeframe besar lebih menentukan arah
TREND_WEIGHT = {Timeframe.H4: 2.0, Timeframe.H1: 1.5}
ENTRY_WEIGHT = 1.0
LEAN_THRESHOLD = 2.0
STRONG_THRESHOLD = 4.0
STRONG_MIN_ADX = 20  # "kuat" hanya bila tren di timeframe grafik juga bertenaga


@dataclass(frozen=True)
class Point:
    tone: Tone
    text: str


@dataclass
class ChartRead:
    timeframe: Timeframe
    lean: Literal["naik", "turun", "netral"]
    strength: Literal["kuat", "sedang", "lemah"]
    score: float
    headline: str
    points: list[Point] = field(default_factory=list)
    watch: str = ""
    price: float | None = None
    support: float | None = None
    resistance: float | None = None


def _adx_text(adx: float) -> str:
    if adx >= 25:
        return "tren kuat"
    if adx >= 20:
        return "tren mulai terbentuk"
    return "tren lemah / pasar mendatar"


def _trend_point(label: str, df: pd.DataFrame) -> tuple[int, Point]:
    t = trend_of(df)
    adx = f"ADX {t.adx:.0f}, {_adx_text(t.adx)}"
    if t.direction == 1:
        return 1, Point("up", f"{label}: tren naik — harga & EMA50 di atas EMA200 ({adx}).")
    if t.direction == -1:
        return -1, Point("down", f"{label}: tren turun — harga & EMA50 di bawah EMA200 ({adx}).")
    return 0, Point("neutral", f"{label}: belum ada tren jelas — harga di antara EMA ({adx}).")


def read_chart(
    frames: dict[Timeframe, pd.DataFrame],
    instrument: Instrument,
    entry: Timeframe,
    offset: float = 0.0,
) -> ChartRead:
    """`frames` berisi indikator untuk `entry`, H1 dan H4 (candle tertutup). Harga yang
    ditampilkan ditambah `offset` kalibrasi broker (sama seperti grafik)."""
    df = frames.get(entry)
    if df is None or len(df) < MIN_BARS:
        return ChartRead(entry, "netral", "lemah", 0.0, "Data chart belum cukup untuk dianalisis.")

    points: list[Point] = []
    score = 0.0
    for tf in (Timeframe.H4, Timeframe.H1):
        if tf == entry or tf not in frames or len(frames[tf]) < MIN_BARS:
            continue
        direction, point = _trend_point(tf.value, frames[tf])
        score += TREND_WEIGHT[tf] * direction
        points.append(point)
    direction, point = _trend_point(f"{entry.value} (grafik)", df)
    score += TREND_WEIGHT.get(entry, ENTRY_WEIGHT) * direction
    points.append(point)

    last, prev = df.iloc[-1], df.iloc[-2]
    close = float(last["close"])

    hist, prev_hist = float(last["macd_hist"]), float(prev["macd_hist"])
    if hist > 0 and hist >= prev_hist:
        score += 0.5
        points.append(
            Point("up", f"Momentum {entry.value} menguat: MACD histogram positif & naik.")
        )
    elif hist < 0 and hist <= prev_hist:
        score -= 0.5
        points.append(
            Point("down", f"Momentum {entry.value} melemah: MACD histogram negatif & turun.")
        )
    else:
        points.append(
            Point("neutral", f"Momentum {entry.value} berubah arah: MACD histogram mulai berbalik.")
        )

    rsi = float(last["rsi"])
    if rsi >= 70:
        points.append(Point("warn", f"RSI {rsi:.0f}: jenuh beli — rawan koreksi turun."))
    elif rsi <= 30:
        points.append(Point("warn", f"RSI {rsi:.0f}: jenuh jual — rawan pantulan naik."))
    elif rsi > 55:
        score += 0.5
        points.append(Point("up", f"RSI {rsi:.0f}: tekanan beli lebih besar."))
    elif rsi < 45:
        score -= 0.5
        points.append(Point("down", f"RSI {rsi:.0f}: tekanan jual lebih besar."))
    else:
        points.append(Point("neutral", f"RSI {rsi:.0f}: seimbang."))

    ema20 = float(last["ema_fast"])
    side = "di atas" if close >= ema20 else "di bawah"
    points.append(
        Point(
            "up" if close >= ema20 else "down",
            f"Harga {side} EMA20 {entry.value} ({price_to_pips(close - ema20, instrument)} pip).",
        )
    )

    recent = df.tail(LEVEL_LOOKBACK)
    highs, lows = recent["high"][recent["high"] > close], recent["low"][recent["low"] < close]
    resistance = float(highs.max()) if len(highs) else None
    support = float(lows.min()) if len(lows) else None

    def level(value: float) -> str:
        return f"{value + offset:.{instrument.digits}f}"

    if resistance is not None:
        pips = price_to_pips(resistance - close, instrument)
        points.append(
            Point(
                "neutral",
                f"Resistance (high {LEVEL_LOOKBACK} candle): {level(resistance)} — "
                f"{pips} pip di atas.",
            )
        )
    if support is not None:
        pips = price_to_pips(close - support, instrument)
        points.append(
            Point(
                "neutral",
                f"Support (low {LEVEL_LOOKBACK} candle): {level(support)} — {pips} pip di bawah.",
            )
        )

    lean: Literal["naik", "turun", "netral"] = (
        "naik" if score >= LEAN_THRESHOLD else "turun" if score <= -LEAN_THRESHOLD else "netral"
    )
    strong = abs(score) >= STRONG_THRESHOLD and float(last["adx"]) >= STRONG_MIN_ADX
    strength: Literal["kuat", "sedang", "lemah"] = (
        "kuat" if strong else "sedang" if lean != "netral" else "lemah"
    )
    if lean == "naik":
        headline = f"Kondisi chart condong NAIK ({strength})"
        watch = f"Yang ditunggu: harga kembali ke EMA20 ({level(ema20)}) lalu candle ditutup naik"
        watch += f", atau tembus resistance {level(resistance)}." if resistance else "."
    elif lean == "turun":
        headline = f"Kondisi chart condong TURUN ({strength})"
        watch = f"Yang ditunggu: harga naik ke EMA20 ({level(ema20)}) lalu candle ditutup turun"
        watch += f", atau tembus support {level(support)}." if support else "."
    else:
        headline = "Kondisi chart NETRAL — arah belum jelas"
        watch = "Yang ditunggu: tren H1 & H4 searah sebelum mempertimbangkan posisi."
    return ChartRead(
        timeframe=entry,
        lean=lean,
        strength=strength,
        score=round(score, 1),
        headline=headline,
        points=points,
        watch=watch,
        price=instrument.round_price(close + offset),
        support=instrument.round_price(support + offset) if support is not None else None,
        resistance=instrument.round_price(resistance + offset) if resistance is not None else None,
    )
