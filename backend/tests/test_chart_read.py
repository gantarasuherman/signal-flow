import numpy as np
import pandas as pd

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.services.chart_read import read_chart
from tests.test_candle_pattern import uptrend

END = pd.Timestamp("2026-10-28 08:00", tz="UTC")


def downtrend(n: int = 300) -> pd.DataFrame:
    from app.analysis.indicators import compute_indicators

    close = 4200 - np.arange(n) * 1.0
    df = pd.DataFrame(
        {"open": close + 0.3, "high": close + 1, "low": close - 1, "close": close},
        index=pd.date_range(end=END, periods=n, freq="15min"),
    )
    return compute_indicators(df)


def test_all_uptrend_leans_up_with_levels(xauusd: Instrument) -> None:
    frames = {tf: uptrend() for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4)}
    r = read_chart(frames, xauusd, Timeframe.M15, offset=1.0)
    assert r.lean == "naik" and r.strength == "kuat" and r.score >= 4
    assert "NAIK" in r.headline and "EMA20" in r.watch
    assert any(p.text.startswith("H4: tren naik") for p in r.points)
    assert r.price == round(float(frames[Timeframe.M15]["close"].iloc[-1]) + 1.0, xauusd.digits)


def test_downtrend_leans_down(xauusd: Instrument) -> None:
    frames = {tf: downtrend() for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4)}
    r = read_chart(frames, xauusd, Timeframe.M15)
    assert r.lean == "turun" and r.score <= -4
    assert any(p.tone == "warn" and "jenuh jual" in p.text for p in r.points)


def test_conflicting_trends_are_neutral(xauusd: Instrument) -> None:
    frames = {Timeframe.M15: uptrend(), Timeframe.H1: downtrend(), Timeframe.H4: downtrend()}
    r = read_chart(frames, xauusd, Timeframe.M15)
    assert r.lean == "turun" or r.lean == "netral"
    frames = {Timeframe.M15: downtrend(), Timeframe.H1: uptrend(), Timeframe.H4: downtrend()}
    assert read_chart(frames, xauusd, Timeframe.M15).lean == "netral"


def test_not_enough_data(xauusd: Instrument) -> None:
    r = read_chart({Timeframe.M15: uptrend(20)}, xauusd, Timeframe.M15)
    assert r.lean == "netral" and "belum cukup" in r.headline


def test_entry_h1_not_counted_twice(xauusd: Instrument) -> None:
    frames = {Timeframe.H1: uptrend(), Timeframe.H4: uptrend()}
    r = read_chart(frames, xauusd, Timeframe.H1)
    assert sum(p.text.startswith("H1") for p in r.points) == 1


def test_weak_adx_caps_strength(xauusd: Instrument) -> None:
    flat = downtrend()
    flat["adx"] = 10.0  # tren searah tetapi tanpa tenaga
    frames = {Timeframe.M15: flat, Timeframe.H1: downtrend(), Timeframe.H4: downtrend()}
    r = read_chart(frames, xauusd, Timeframe.M15)
    assert r.lean == "turun" and r.strength == "sedang"
