# ruff: noqa: E501  (tabel data candle lebih mudah dibaca satu baris per pola)
import pandas as pd
import pytest

from app.strategies.patterns import describe, detect_patterns, pattern_bias

DOWN = [(110, 110.5, 107.5, 108), (108, 108.5, 105.5, 106), (106, 106.5, 103.5, 104)]
UP = [(90, 92.5, 89.5, 92), (92, 94.5, 91.5, 94), (94, 96.5, 93.5, 96)]


def df(*candles: tuple[float, float, float, float]) -> pd.DataFrame:
    """Candle (open, high, low, close) dengan ATR tetap 1.0."""
    rows = [{"open": o, "high": h, "low": lo, "close": c, "atr": 1.0} for o, h, lo, c in candles]
    return pd.DataFrame(rows, index=pd.RangeIndex(len(rows)))


def names(*candles: tuple[float, float, float, float]) -> set[str]:
    return {p.name for p in detect_patterns(df(*candles))}


@pytest.mark.parametrize(
    ("candles", "expected"),
    [
        # satu candle — konteks dari 3 candle sebelumnya
        ([*DOWN, (104, 104.2, 103.6, 103.8), (103.8, 104, 101, 103.9)], "Hammer"),
        ([*UP, (96, 96.3, 95.8, 96.1), (96.1, 96.3, 93.5, 96.2)], "Hanging Man"),
        ([*DOWN, (104, 104.2, 103.6, 103.8), (103.8, 106.8, 103.75, 103.95)], "Inverted Hammer"),
        ([*UP, (96, 96.3, 95.8, 96.1), (96.1, 99, 96.05, 96.25)], "Shooting Star"),
        ([*DOWN, (104, 104.2, 103.6, 103.8), (100, 101, 99, 100.1)], "Spinning Top"),
        # dua candle
        ([*DOWN, (104, 104.5, 103.5, 104), (104, 104.2, 101.9, 102), (101.9, 103.6, 101.8, 103.5)], "Piercing Line"),
        ([*UP, (96, 96.5, 95.5, 96), (96, 98.1, 95.9, 98), (98.1, 98.2, 96.4, 96.5)], "Dark Cloud Cover"),
        ([*DOWN, (104, 104.5, 103.5, 104), (104, 104.1, 102.9, 103), (102.9, 104.6, 102.8, 104.5)], "Bullish Engulfing"),
        ([*UP, (96, 96.5, 95.5, 96), (96, 97.1, 95.9, 97), (97.1, 97.2, 95.4, 95.5)], "Bearish Engulfing"),
        ([*DOWN, (104, 104.5, 103.5, 104), (104, 104.1, 102, 102.4), (102.4, 103.5, 102.02, 103.3)], "Tweezer Bottom"),
        ([*UP, (96, 96.5, 95.5, 96), (96, 98, 95.9, 97.6), (97.6, 98.03, 96.5, 96.7)], "Tweezer Top"),
        # tiga candle
        ([*UP, (96, 98.1, 95.9, 98), (98.1, 98.4, 97.9, 98.2), (98.1, 98.2, 96.2, 96.4)], "Evening Star"),
        ([*DOWN, (104, 104.1, 101.9, 102), (101.9, 102.1, 101.6, 101.8), (101.9, 103.8, 101.8, 103.6)], "Morning Star"),
        ([*DOWN, (100, 101.1, 99.9, 101), (101, 102.1, 100.9, 102), (102, 103.1, 101.9, 103)], "Three White Soldiers"),
        ([*UP, (100, 100.1, 98.9, 99), (99, 99.1, 97.9, 98), (98, 98.1, 96.9, 97)], "Three Black Crows"),
    ],
)  # fmt: skip
def test_detects_pattern(candles: list[tuple[float, float, float, float]], expected: str) -> None:
    assert expected in names(*candles)


def test_hammer_shape_needs_context() -> None:
    # Bentuk hammer setelah pasar datar bukan Hammer maupun Hanging Man
    flat = [(100, 100.3, 99.7, 100), (100, 100.3, 99.7, 100.05), (100, 100.3, 99.7, 99.95)]
    found = names(*flat, (100, 100.2, 99.8, 100), (100, 100.2, 97.5, 100.1))
    assert not found & {"Hammer", "Hanging Man"}


def test_bias_and_description() -> None:
    bull = detect_patterns(df(*DOWN, (104, 104.2, 103.6, 103.8), (103.8, 104, 101, 103.9)))
    assert pattern_bias(bull) == 1
    assert "Hammer (potensi pembalikan naik)" in describe(bull)
    spinning = detect_patterns(df(*DOWN, (104, 104.2, 103.6, 103.8), (100, 101, 99, 100.1)))
    assert pattern_bias(spinning) == 0  # ragu-ragu → tidak mengonfirmasi arah mana pun
    assert describe([]) == "tidak ada pola khusus"
