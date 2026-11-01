"""Ringkasan kondisi chart dalam bahasa sehari-hari (tren, momentum, level penting).

Bukan sinyal strategi teruji: dipakai untuk menjelaskan apa yang terlihat di grafik, termasuk
saat strategi menunggu atau dinonaktifkan. Aturan tren sama dengan strategi (`trend_of`)."""

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.analysis.risk import price_to_pips
from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.strategies.common import row_trend, trend_of

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


@dataclass(frozen=True)
class LeanEvent:
    """Arah analisis berubah di candle `time` (waktu buka): BUY saat menjadi NAIK, SELL saat
    menjadi TURUN, CLOSE saat arah sebelumnya hilang. `result_pips` (bersih setelah spread)
    hanya untuk CLOSE, dihitung dari harga tutup candle BUY/SELL ke harga tutup candle ini."""

    time: pd.Timestamp
    action: Literal["BUY", "SELL", "CLOSE"]
    price: float
    result_pips: float | None = None


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
    events: list[LeanEvent] = field(default_factory=list)


def score_series(frames: dict[Timeframe, pd.DataFrame], entry: Timeframe) -> pd.Series:
    """Skor analisis untuk SETIAP candle frame `entry`, tanpa mengintip masa depan: tren H1/H4
    diambil dari candle besar terakhir yang sudah tutup saat candle `entry` itu tutup."""
    df = frames[entry]
    score = pd.Series(0.0, index=df.index)
    entry_close = df.index + entry.delta
    for tf in (Timeframe.H4, Timeframe.H1):
        big = frames.get(tf)
        if tf == entry or big is None or len(big) < MIN_BARS:
            continue
        trend = big.apply(row_trend, axis=1).astype(float)
        trend.index = big.index + tf.delta  # waktu tutup candle besar
        aligned = trend.reindex(trend.index.union(entry_close)).ffill().reindex(entry_close)
        score += TREND_WEIGHT[tf] * aligned.fillna(0.0).to_numpy()
    score += TREND_WEIGHT.get(entry, ENTRY_WEIGHT) * df.apply(row_trend, axis=1)
    hist, prev = df["macd_hist"], df["macd_hist"].shift()
    score += 0.5 * ((hist > 0) & (hist >= prev)) - 0.5 * ((hist < 0) & (hist <= prev))
    rsi = df["rsi"]
    score += 0.5 * ((rsi > 55) & (rsi < 70)) - 0.5 * ((rsi < 45) & (rsi > 30))
    return score


def lean_of(score: float) -> Literal["naik", "turun", "netral"]:
    return "naik" if score >= LEAN_THRESHOLD else "turun" if score <= -LEAN_THRESHOLD else "netral"


def lean_events(
    df: pd.DataFrame, score: pd.Series, instrument: Instrument, spread_pips: float
) -> list[LeanEvent]:
    """Titik BUY/SELL/CLOSE setiap arah analisis berubah. Berbalik langsung (NAIK → TURUN)
    menghasilkan CLOSE lalu posisi baru di candle yang sama."""
    events: list[LeanEvent] = []
    side, entry_price = 0, 0.0
    for t, value, close in zip(df.index, score, df["close"], strict=True):
        lean = lean_of(value)
        direction = 1 if lean == "naik" else -1 if lean == "turun" else 0
        if direction == side:
            continue
        if side:
            pips = (close - entry_price) * side / instrument.pip_size - spread_pips
            events.append(LeanEvent(t, "CLOSE", float(close), round(pips, 1)))
        if direction:
            events.append(LeanEvent(t, "BUY" if direction > 0 else "SELL", float(close)))
        side, entry_price = direction, close
    return events


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
    spread_pips: float = 0.0,
) -> ChartRead:
    """`frames` berisi indikator untuk `entry`, H1 dan H4 (candle tertutup). Harga yang
    ditampilkan ditambah `offset` kalibrasi broker (sama seperti grafik). Arah & skor dihitung
    dengan `score_series` yang sama dengan titik BUY/SELL/CLOSE di grafik."""
    df = frames.get(entry)
    if df is None or len(df) < MIN_BARS:
        return ChartRead(entry, "netral", "lemah", 0.0, "Data chart belum cukup untuk dianalisis.")

    scores = score_series(frames, entry)
    score = float(scores.iloc[-1])
    events = lean_events(df, scores, instrument, spread_pips)
    points: list[Point] = []
    for tf in (Timeframe.H4, Timeframe.H1):
        if tf == entry or tf not in frames or len(frames[tf]) < MIN_BARS:
            continue
        points.append(_trend_point(tf.value, frames[tf])[1])
    points.append(_trend_point(f"{entry.value} (grafik)", df)[1])

    last, prev = df.iloc[-1], df.iloc[-2]
    close = float(last["close"])

    hist, prev_hist = float(last["macd_hist"]), float(prev["macd_hist"])
    if hist > 0 and hist >= prev_hist:
        points.append(
            Point("up", f"Momentum {entry.value} menguat: MACD histogram positif & naik.")
        )
    elif hist < 0 and hist <= prev_hist:
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
        points.append(Point("up", f"RSI {rsi:.0f}: tekanan beli lebih besar."))
    elif rsi < 45:
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

    lean = lean_of(score)
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
        events=[
            LeanEvent(e.time, e.action, instrument.round_price(e.price + offset), e.result_pips)
            for e in events
        ],
    )
