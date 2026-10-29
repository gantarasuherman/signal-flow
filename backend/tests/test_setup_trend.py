from datetime import timedelta

import pandas as pd
import pytest

from app.core.instruments import Instrument
from app.strategies import Action, StrategyContext, create_strategy
from app.strategies.features import SetupFilter, potential_setup
from tests.test_ai_groq import END, force_trend, frame


@pytest.fixture
def frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """M15 dengan pullback BUY yang valid: sentuh EMA20, candle terakhir bullish naik."""
    m15 = frame(300, timedelta(minutes=15))
    last, prev, touch = m15.index[-1], m15.index[-2], m15.index[-3]
    m15.loc[touch, "low"] = m15.loc[touch, "ema_fast"] - 0.1
    ema20 = m15.loc[last, "ema_fast"]
    m15.loc[prev, "close"] = ema20 + 0.5
    m15.loc[last, ["open", "close", "rsi", "ema_mid"]] = [ema20 + 0.6, ema20 + 2, 55, ema20]
    h1 = force_trend(frame(300, timedelta(hours=1)), 1)
    h4 = force_trend(frame(300, timedelta(hours=4)), 1)
    return m15, h1, h4


def test_base_filter_finds_pullback(frames: tuple[pd.DataFrame, ...]) -> None:
    m15, h1, h4 = frames
    setup = potential_setup(m15, h1, h4)
    assert setup is not None and setup.direction == 1 and setup.kind == "pullback"


def test_confirm_candle_rejects_bearish_last_candle(frames: tuple[pd.DataFrame, ...]) -> None:
    m15, h1, h4 = frames
    m15 = m15.copy()
    last = m15.index[-1]
    m15.loc[last, "open"] = m15.loc[last, "close"] + 0.3  # candle terakhir bearish
    assert potential_setup(m15, h1, h4) is not None
    assert potential_setup(m15, h1, h4, SetupFilter(confirm_candle=True)) is None


def test_strict_h4_and_extension(frames: tuple[pd.DataFrame, ...]) -> None:
    m15, h1, _ = frames
    flat_h4 = force_trend(frame(300, timedelta(hours=4)), 0)
    assert potential_setup(m15, h1, flat_h4) is not None
    assert potential_setup(m15, h1, flat_h4, SetupFilter(strict_h4=True)) is None

    far = m15.copy()
    far.loc[far.index[-1], "ema_mid"] = far.loc[far.index[-1], "close"] - 10 * far["atr"].iloc[-1]
    assert potential_setup(far, h1, frames[2], SetupFilter(max_extension_atr=2.0)) is None


def test_setup_trend_strategy_signal(frames: tuple[pd.DataFrame, ...], xauusd: Instrument) -> None:
    m15, h1, h4 = frames
    now = END.to_pydatetime() + timedelta(minutes=15)
    s = create_strategy("setup_trend", {"strict_h4": True, "confirm_candle": True})
    d = s.evaluate(StrategyContext(xauusd, now, m15, h1, h4, 0.0))
    atr = float(m15["atr"].iloc[-1])
    assert d.action is Action.BUY
    assert d.entry - d.stop_loss == pytest.approx(1.5 * atr, abs=0.02)
    assert d.take_profit - d.entry == pytest.approx(3.0 * atr, abs=0.02)

    session = create_strategy("setup_trend", {"entry_hours_utc": [14, 15]})  # now = 08:15 UTC
    assert session.evaluate(StrategyContext(xauusd, now, m15, h1, h4, 0.0)).action is Action.WAIT
