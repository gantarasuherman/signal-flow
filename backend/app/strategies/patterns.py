"""Deteksi pola candlestick klasik pada candle terakhir (dihitung kode).

bias: +1 = potensi naik, -1 = potensi turun, 0 = ragu-ragu (indecision).
Konteks "setelah turun/naik" diukur dari arah 3 candle sebelum pola (close vs close).
Definisi disesuaikan untuk forex/emas 24 jam (gap jarang terjadi, jadi syarat gap dilonggarkan).
"""

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

PRIOR_BARS = 3


@dataclass(frozen=True)
class Pattern:
    name: str
    bias: int  # +1 naik, -1 turun, 0 ragu-ragu
    meaning: str


PATTERN_INFO = {
    "Evening Star": (-1, "potensi pembalikan turun"),
    "Morning Star": (1, "potensi pembalikan naik"),
    "Hammer": (1, "potensi pembalikan naik"),
    "Inverted Hammer": (1, "potensi pembalikan naik"),
    "Hanging Man": (-1, "potensi pembalikan turun"),
    "Shooting Star": (-1, "potensi pembalikan turun"),
    "Three White Soldiers": (1, "tekanan beli kuat"),
    "Three Black Crows": (-1, "tekanan jual kuat"),
    "Piercing Line": (1, "potensi pembalikan naik"),
    "Dark Cloud Cover": (-1, "potensi pembalikan turun"),
    "Bullish Engulfing": (1, "potensi pembalikan naik"),
    "Bearish Engulfing": (-1, "potensi pembalikan turun"),
    "Tweezer Bottom": (1, "potensi pembalikan naik"),
    "Tweezer Top": (-1, "potensi pembalikan turun"),
    "Spinning Top": (0, "ragu-ragu, arah belum jelas"),
}


def _make(name: str) -> Pattern:
    bias, meaning = PATTERN_INFO[name]
    return Pattern(name, bias, meaning)


def _parts(row: pd.Series) -> tuple[float, float, float, float, float, float, float]:
    o, h, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - lo
    return o, h, lo, c, body, upper, lower


def detect_patterns(df: pd.DataFrame, atr: float | None = None) -> list[Pattern]:
    """Pola yang BERAKHIR di candle terakhir `df` (butuh minimal 3 + PRIOR_BARS candle)."""
    if len(df) < 3:
        return []
    if atr is None and "atr" in df:
        atr = float(df["atr"].iloc[-1])
    if not atr or atr != atr:  # None, 0, atau NaN → rata-rata range 14 candle
        atr = float((df["high"] - df["low"]).tail(14).mean()) or 1e-9
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    o1, h1, l1, cl1, b1, _, _ = _parts(c1)
    o2, h2, l2, cl2, b2, up2, lo2 = _parts(c2)
    o3, h3, l3, cl3, b3, up3, lo3 = _parts(c3)
    rng3 = (h3 - l3) or 1e-9

    def move_before(n_pattern: int) -> int:
        """Arah harga PRIOR_BARS candle sebelum pola (1 naik, -1 turun, 0 datar)."""
        end = -n_pattern - 1
        start = end - PRIOR_BARS
        if len(df) < -start:
            return 0  # histori belum cukup untuk menilai konteks
        diff = float(df["close"].iloc[end]) - float(df["close"].iloc[start])
        if abs(diff) < 0.3 * atr:
            return 0
        return 1 if diff > 0 else -1

    found: list[Pattern] = []
    bull3, bear3 = cl3 > o3, cl3 < o3
    bull2, bear2 = cl2 > o2, cl2 < o2

    # --- satu candle ---
    small_body = b3 <= 0.35 * rng3
    if b3 <= 0.3 * rng3 and up3 >= 0.25 * rng3 and lo3 >= 0.25 * rng3:
        found.append(_make("Spinning Top"))
    elif lo3 >= 2 * max(b3, 1e-9) and up3 <= 0.25 * rng3 and small_body:
        prior = move_before(1)
        if prior == -1:
            found.append(_make("Hammer"))
        elif prior == 1:
            found.append(_make("Hanging Man"))
    elif up3 >= 2 * max(b3, 1e-9) and lo3 <= 0.25 * rng3 and small_body:
        prior = move_before(1)
        if prior == -1:
            found.append(_make("Inverted Hammer"))
        elif prior == 1:
            found.append(_make("Shooting Star"))

    # --- dua candle ---
    prior2 = move_before(2)
    mid2 = (o2 + cl2) / 2
    if bear2 and bull3 and b2 >= 0.5 * atr and o3 <= cl2 and mid2 < cl3 < o2 and prior2 <= 0:
        found.append(_make("Piercing Line"))
    if bull2 and bear3 and b2 >= 0.5 * atr and o3 >= cl2 and o2 < cl3 < mid2 and prior2 >= 0:
        found.append(_make("Dark Cloud Cover"))
    if bear2 and bull3 and o3 <= cl2 and cl3 >= o2 and b3 > b2 and prior2 <= 0:
        found.append(_make("Bullish Engulfing"))
    if bull2 and bear3 and o3 >= cl2 and cl3 <= o2 and b3 > b2 and prior2 >= 0:
        found.append(_make("Bearish Engulfing"))
    tol = 0.1 * atr
    if bear2 and bull3 and abs(l2 - l3) <= tol and prior2 == -1:
        found.append(_make("Tweezer Bottom"))
    if bull2 and bear3 and abs(h2 - h3) <= tol and prior2 == 1:
        found.append(_make("Tweezer Top"))

    # --- tiga candle ---
    mid1 = (o1 + cl1) / 2
    star_small = b2 <= 0.35 * b1 if b1 else False
    if (
        cl1 > o1
        and b1 >= 0.6 * atr
        and star_small
        and min(o2, cl2) >= cl1 - 0.1 * atr
        and bear3
        and cl3 < mid1
    ):
        found.append(_make("Evening Star"))
    if (
        cl1 < o1
        and b1 >= 0.6 * atr
        and star_small
        and max(o2, cl2) <= cl1 + 0.1 * atr
        and bull3
        and cl3 > mid1
    ):
        found.append(_make("Morning Star"))
    three = (c1, c2, c3)
    strong_bodies = min(b1, b2, b3) >= 0.4 * atr
    # Tiga candle searah dengan badan kuat dan sumbu kecil di ujung arahnya
    if (
        strong_bodies
        and all(r["close"] > r["open"] for r in three)
        and cl1 < cl2 < cl3
        and all(_parts(r)[5] <= 0.4 * _parts(r)[4] for r in three)
    ):
        found.append(_make("Three White Soldiers"))
    if (
        strong_bodies
        and all(r["close"] < r["open"] for r in three)
        and cl1 > cl2 > cl3
        and all(_parts(r)[6] <= 0.4 * _parts(r)[4] for r in three)
    ):
        found.append(_make("Three Black Crows"))
    return found


def pattern_bias(patterns: list[Pattern]) -> int:
    """+1 bila hanya ada pola naik, -1 bila hanya pola turun, 0 bila campur/ragu/tidak ada."""
    biases = {p.bias for p in patterns if p.bias}
    if len(biases) == 1 and not any(p.bias == 0 for p in patterns):
        return biases.pop()
    return 0


def describe(patterns: list[Pattern]) -> str:
    if not patterns:
        return "tidak ada pola khusus"
    return ", ".join(f"{p.name} ({p.meaning})" for p in patterns)


# ---------- konteks pola: lokasi + tren ----------

SCAN_WINDOW = 20  # candle yang cukup untuk detect_patterns (pola 3 candle + konteks + ATR)
LEVEL_LOOKBACK = 20
STRENGTH_TEXT = {3: "kuat", 2: "sedang", 1: "lemah"}


@dataclass(frozen=True)
class PatternRead:
    pattern: Pattern
    strength: int  # 1 lemah, 2 sedang, 3 kuat (0 untuk pola ragu-ragu)
    at_level: bool
    with_trend: bool
    note: str

    @property
    def strength_text(self) -> str:
        return STRENGTH_TEXT.get(self.strength, "netral")


def level_note(df: pd.DataFrame, bias: int, atr: float) -> str | None:
    """Apakah pola muncul di area support (pola naik) / resistance (pola turun):
    menyentuh Bollinger luar, swing 20 candle, atau EMA50."""
    if bias == 0 or len(df) < 4:
        return None
    window = df.iloc[-3:]
    before = df.iloc[-LEVEL_LOOKBACK - 3 : -3]
    last = df.iloc[-1]
    near = 0.3 * atr
    if bias == 1:
        low = float(window["low"].min())
        if "bb_lower" in df and pd.notna(last["bb_lower"]) and low <= last["bb_lower"] + near:
            return "menyentuh Bollinger bawah"
        if len(before) and low <= float(before["low"].min()) + near:
            return "di area swing low (support)"
        if "ema_mid" in df and pd.notna(last["ema_mid"]) and abs(low - last["ema_mid"]) <= near:
            return "memantul di EMA50"
    else:
        high = float(window["high"].max())
        if "bb_upper" in df and pd.notna(last["bb_upper"]) and high >= last["bb_upper"] - near:
            return "menyentuh Bollinger atas"
        if len(before) and high >= float(before["high"].max()) - near:
            return "di area swing high (resistance)"
        if "ema_mid" in df and pd.notna(last["ema_mid"]) and abs(high - last["ema_mid"]) <= near:
            return "tertahan di EMA50"
    return None


def assess(df: pd.DataFrame, pattern: Pattern, trend: int, atr: float) -> PatternRead:
    """Nilai kekuatan pola: +1 di area support/resistance, +1 searah tren, dasar 1."""
    if pattern.bias == 0:
        return PatternRead(pattern, 0, False, False, "pasar ragu-ragu; tunggu konfirmasi")
    level = level_note(df, pattern.bias, atr)
    with_trend = trend == pattern.bias
    against = trend == -pattern.bias
    strength = 1 + bool(level) + with_trend
    parts = [level or "bukan di area support/resistance"]
    if with_trend:
        parts.append("searah tren")
    elif against:
        parts.append("melawan tren (butuh konfirmasi)")
    else:
        parts.append("tren datar")
    return PatternRead(pattern, strength, bool(level), with_trend, ", ".join(parts))


def read_patterns(df: pd.DataFrame, trend: int) -> list[PatternRead]:
    """Pola pada candle terakhir `df` beserta kekuatannya."""
    if len(df) < 3:
        return []
    atr = float(df["atr"].iloc[-1]) if "atr" in df else float("nan")
    if atr != atr or atr <= 0:
        atr = float((df["high"] - df["low"]).tail(14).mean()) or 1e-9
    return [assess(df, p, trend, atr) for p in detect_patterns(df, atr)]


def scan_patterns(
    df: pd.DataFrame, bars: int, trend_of_row: Callable[[pd.Series], int] | None = None
) -> list[tuple[pd.Timestamp, PatternRead]]:
    """Pola yang muncul di setiap candle dari `bars` candle terakhir (untuk penanda grafik)."""
    out: list[tuple[pd.Timestamp, PatternRead]] = []
    for i in range(max(len(df) - bars, 3), len(df)):
        window = df.iloc[max(0, i - SCAN_WINDOW - LEVEL_LOOKBACK) : i + 1]
        trend = trend_of_row(window.iloc[-1]) if trend_of_row else 0
        out.extend((df.index[i], r) for r in read_patterns(window, trend))
    return out
