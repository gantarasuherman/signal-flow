import numpy as np
import pandas as pd
import pytest

from app.analysis.indicators import (
    adx,
    atr,
    bollinger,
    compute_indicators,
    ema,
    macd,
    rsi,
    wilder_smooth,
)

# Data contoh RSI klasik (Wilder / StockCharts)
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
]  # fmt: skip


def ohlc(close: list[float] | np.ndarray, spread: float = 1.0) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + spread, "low": close - spread, "close": close}
    )


def test_ema_matches_recursive_definition() -> None:
    s = pd.Series(np.arange(1, 31, dtype=float))
    result = ema(s, 10)
    assert result.iloc[:9].isna().all()
    alpha = 2 / 11
    manual = s.iloc[0]
    for value in s.iloc[1:]:
        manual = alpha * value + (1 - alpha) * manual
    assert result.iloc[-1] == pytest.approx(manual)


def test_wilder_smooth_seed_is_simple_average() -> None:
    s = pd.Series([np.nan, 1, 2, 3, 4, 5], dtype=float)
    result = wilder_smooth(s, 3)
    assert result.iloc[3] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx((2.0 * 2 + 4) / 3)


def test_rsi_reference_values() -> None:
    # Tabel StockCharts menampilkan 70.53, 66.32, ... karena membulatkan rata-rata di tiap
    # baris; perhitungan presisi penuh (Wilder) menghasilkan nilai di bawah.
    result = rsi(pd.Series(WILDER_CLOSES), 14)
    assert result.iloc[:14].isna().all()
    expected = [70.46, 66.25, 66.48, 69.35, 66.29, 57.92]
    assert result.iloc[14:].round(2).tolist() == expected


def test_rsi_extremes() -> None:
    assert rsi(pd.Series(np.arange(30, dtype=float)), 14).iloc[-1] == 100
    assert rsi(pd.Series(np.arange(30, 0, -1, dtype=float)), 14).iloc[-1] == pytest.approx(0)
    assert rsi(pd.Series([5.0] * 30), 14).iloc[-1] == 50


def test_atr_constant_range() -> None:
    result = atr(ohlc([100.0] * 40, spread=1.0), 14)
    assert result.iloc[-1] == pytest.approx(2.0)


def test_macd_on_linear_trend() -> None:
    # Untuk deret linier dengan slope 1, EMA12 − EMA26 menuju (26 − 12) / 2 = 7
    line, signal, hist = macd(pd.Series(np.arange(300, dtype=float)))
    assert line.iloc[-1] == pytest.approx(7.0, abs=1e-6)
    assert signal.iloc[-1] == pytest.approx(7.0, abs=1e-6)
    assert hist.iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_bollinger_constant_series_collapses() -> None:
    lower, mid, upper = bollinger(pd.Series([10.0] * 25), 20, 2)
    assert lower.iloc[-1] == mid.iloc[-1] == upper.iloc[-1] == 10.0


def test_adx_strong_trend_vs_flat() -> None:
    trend = adx(ohlc(np.arange(100, 200, dtype=float)), 14)
    assert trend[0].iloc[-1] > 50
    assert trend[1].iloc[-1] > trend[2].iloc[-1]  # +DI > -DI

    rng = np.random.default_rng(1)
    flat = adx(ohlc(100 + rng.normal(0, 0.5, 200)), 14)
    assert flat[0].iloc[-1] < 30


def test_indicators_are_causal() -> None:
    """Nilai indikator di masa lalu tidak boleh berubah saat data baru ditambahkan."""
    rng = np.random.default_rng(7)
    df = ohlc(100 + np.cumsum(rng.normal(0, 1, 400)))
    full = compute_indicators(df)
    partial = compute_indicators(df.iloc[:300])
    cols = ["ema_fast", "ema_slow", "rsi", "macd", "atr", "bb_upper", "adx"]
    pd.testing.assert_frame_equal(full[cols].iloc[:300], partial[cols])
