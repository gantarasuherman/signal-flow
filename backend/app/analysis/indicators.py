"""Indikator teknikal. Semua fungsi kausal: nilai di baris i hanya memakai data <= i,
sehingga aman dipakai untuk backtest tanpa bocoran data masa depan."""

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


class IndicatorConfig(BaseModel):
    ema_fast: int = Field(default=20, ge=2)
    ema_mid: int = Field(default=50, ge=2)
    ema_slow: int = Field(default=200, ge=2)
    rsi_period: int = Field(default=14, ge=2)
    macd_fast: int = Field(default=12, ge=2)
    macd_slow: int = Field(default=26, ge=2)
    macd_signal: int = Field(default=9, ge=2)
    atr_period: int = Field(default=14, ge=2)
    bb_period: int = Field(default=20, ge=2)
    bb_std: float = Field(default=2.0, gt=0)
    adx_period: int = Field(default=14, ge=2)


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Smoothing Wilder (RMA) dengan nilai awal rata-rata sederhana `period` data pertama."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    valid = ~np.isnan(values)
    if not valid.any():
        return pd.Series(out, index=series.index)
    first = int(np.argmax(valid))
    seed_end = first + period
    if seed_end > len(values):
        return pd.Series(out, index=series.index)
    out[seed_end - 1] = values[first:seed_end].mean()
    for i in range(seed_end, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return pd.Series(out, index=series.index)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    avg_gain = wilder_smooth(delta.clip(lower=0), period)
    avg_loss = wilder_smooth(-delta.clip(upper=0), period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        result = 100 - 100 / (1 + rs)
    result = result.where(avg_loss != 0, 100.0)
    result = result.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return result.where(avg_gain.notna())


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return wilder_smooth(true_range(df), period)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    signal_line = ema(line, signal)
    return line, signal_line, line - signal_line


def bollinger(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid - num_std * std, mid, mid + num_std * std


def adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Mengembalikan (ADX, +DI, -DI)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    plus_dm.iloc[0] = minus_dm.iloc[0] = np.nan
    tr = true_range(df)
    tr.iloc[0] = np.nan

    atr_s = wilder_smooth(tr, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * wilder_smooth(plus_dm, period) / atr_s
        minus_di = 100 * wilder_smooth(minus_dm, period) / atr_s
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0.0).where(plus_di.notna())
    return wilder_smooth(dx, period), plus_di, minus_di


def compute_indicators(df: pd.DataFrame, cfg: IndicatorConfig | None = None) -> pd.DataFrame:
    """Tambahkan kolom indikator ke salinan DataFrame OHLC."""
    cfg = cfg or IndicatorConfig()
    out = df.copy()
    close = out["close"]
    out["ema_fast"] = ema(close, cfg.ema_fast)
    out["ema_mid"] = ema(close, cfg.ema_mid)
    out["ema_slow"] = ema(close, cfg.ema_slow)
    out["rsi"] = rsi(close, cfg.rsi_period)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(
        close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
    )
    out["atr"] = atr(out, cfg.atr_period)
    out["bb_lower"], out["bb_mid"], out["bb_upper"] = bollinger(close, cfg.bb_period, cfg.bb_std)
    out["adx"], out["plus_di"], out["minus_di"] = adx(out, cfg.adx_period)
    return out
