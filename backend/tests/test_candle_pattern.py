from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from app.analysis.indicators import compute_indicators
from app.api.patterns import TimeframePatterns, conclude, pattern_marks
from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.strategies import Action, StrategyContext, create_strategy
from app.strategies.patterns import detect_patterns, read_patterns

END = pd.Timestamp("2026-10-28 08:00", tz="UTC")


def downtrend_then_hammer(n: int = 300) -> pd.DataFrame:
    """Harga turun bertahap lalu candle terakhir Hammer di titik terendah (support)."""
    rng = np.random.default_rng(1)
    close = 4100 - np.arange(n) * 0.4 + rng.normal(0, 0.2, n)
    df = pd.DataFrame(
        {"open": close + 0.3, "high": close + 0.6, "low": close - 0.6, "close": close},
        index=pd.DatetimeIndex([END - timedelta(minutes=15) * (n - 1 - i) for i in range(n)]),
    )
    last = df.index[-1]
    base = float(df["close"].iloc[-2])
    # badan kecil di atas, sumbu bawah panjang menembus low sebelumnya
    df.loc[last, ["open", "close", "high", "low"]] = [base, base + 0.3, base + 0.35, base - 3.0]
    return compute_indicators(df)


def uptrend(n: int = 300, step: timedelta = timedelta(hours=1)) -> pd.DataFrame:
    close = 3900 + np.arange(n) * 1.0
    df = pd.DataFrame(
        {"open": close - 0.3, "high": close + 1, "low": close - 1, "close": close},
        index=pd.DatetimeIndex([END - step * (n - 1 - i) for i in range(n)]),
    )
    return compute_indicators(df)


def test_hammer_at_support_is_read_with_strength() -> None:
    df = downtrend_then_hammer()
    assert [p.name for p in detect_patterns(df)] == ["Hammer"]
    (read,) = read_patterns(df, trend=1)
    assert read.at_level and read.with_trend and read.strength == 3
    (against,) = read_patterns(df, trend=-1)
    assert against.strength == 2 and "melawan tren" in against.note


def test_markers_and_conclusion() -> None:
    marks = pattern_marks(downtrend_then_hammer(), 50)
    assert marks[-1].name == "Hammer" and marks[-1].bias == 1
    assert all(m.bias != 0 for m in marks)  # Spinning Top tidak jadi penanda

    def frames(h1_trend: str) -> list[TimeframePatterns]:
        return [
            TimeframePatterns(
                timeframe=Timeframe.M15, trend="naik", candle_time=0, patterns=[marks[-1]]
            ),
            TimeframePatterns(timeframe=Timeframe.H1, trend=h1_trend, candle_time=0, patterns=[]),
        ]

    assert marks[-1].strength >= 2
    assert conclude(frames("naik")).bias == "BUY"
    against = conclude(frames("turun"))
    assert against.bias == "MIXED" and "melawan tren H1" in against.text
    assert conclude([]).bias == "NONE"


def ctx(inst: Instrument, h1: pd.DataFrame) -> StrategyContext:
    m15 = downtrend_then_hammer()
    return StrategyContext(
        inst, END.to_pydatetime() + timedelta(minutes=15), m15, h1, h1, spread_price=0.25
    )


def test_strategy_buys_hammer_with_h1_uptrend(xauusd: Instrument) -> None:
    s = create_strategy("candle_pattern")
    d = s.evaluate(ctx(xauusd, uptrend()))
    assert d.action is Action.BUY and "Hammer" in d.reasons[0]
    low = float(downtrend_then_hammer()["low"].iloc[-3:].min())
    assert d.stop_loss is not None and d.stop_loss < low  # SL di bawah ujung pola
    assert d.details["risk_reward"] == pytest.approx(2.0, abs=0.05)


def test_strategy_rejects_pattern_against_h1_trend(xauusd: Instrument) -> None:
    down = uptrend().iloc[::-1].copy()
    down.index = uptrend().index
    down = compute_indicators(down[["open", "high", "low", "close"]])
    d = create_strategy("candle_pattern").evaluate(ctx(xauusd, down))
    assert d.action is Action.WAIT and "melawan tren" in d.reasons[0]
    free = create_strategy("candle_pattern", {"trend_filter": "none"})
    assert free.evaluate(ctx(xauusd, down)).action is Action.BUY


def test_profit_lock_closes_winning_sell_on_hammer(xauusd: Instrument) -> None:
    from app.analysis.engine import step
    from app.analysis.profit_lock import ProfitCloseConfig
    from app.strategies import ActiveSignalView

    c = ctx(xauusd, uptrend())
    m15 = c.m15
    entry_time = m15.index[-20].to_pydatetime()
    entry = float(m15["close"].iloc[-20])  # SELL di atas; harga turun ±8 sejak itu
    win = ActiveSignalView(1, Action.SELL, entry, entry + 3.0, entry - 30.0, entry_time)
    hold = create_strategy("disabled")
    with_pos = StrategyContext(c.instrument, c.now, m15, c.h1, c.h4, 0.25, win)

    res = step(hold, with_pos, [], 999, ProfitCloseConfig())
    assert res.exit is not None and "Ambil untung: pola Hammer" in res.exit.reason
    assert res.exit.result_pips > 0

    # untung belum 1R → tetap ditahan; fitur bisa dimatikan
    small = ActiveSignalView(1, Action.SELL, entry, entry + 50.0, entry - 90.0, entry_time)
    tiny = StrategyContext(c.instrument, c.now, m15, c.h1, c.h4, 0.25, small)
    assert step(hold, tiny, [], 999, ProfitCloseConfig()).exit is None
    assert step(hold, with_pos, [], 999, ProfitCloseConfig(enabled=False)).exit is None
