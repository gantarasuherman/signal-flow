from datetime import UTC, datetime

import pandas as pd
import pytest

from app.core.instruments import Instrument
from app.strategies import (
    Action,
    ActiveSignalView,
    StrategyContext,
    confidence_label,
    create_strategy,
)
from tests.conftest import make_frame

NOW = datetime(2026, 10, 28, 6, 15, tzinfo=UTC)


def trend_frame(direction: int, adx: float = 30) -> pd.DataFrame:
    """Frame H1/H4: harga & EMA tersusun sesuai arah tren."""
    base = {"open": 100, "high": 101, "low": 99, "atr": 1, "rsi": 55, "macd": 0, "macd_signal": 0,
            "macd_hist": 0, "adx": adx}  # fmt: skip
    if direction == 1:
        row = {**base, "close": 103, "ema_fast": 102, "ema_mid": 101, "ema_slow": 100}
    elif direction == -1:
        row = {**base, "close": 97, "ema_fast": 98, "ema_mid": 99, "ema_slow": 100}
    else:
        row = {**base, "close": 100, "ema_fast": 100, "ema_mid": 101, "ema_slow": 99}
    return make_frame([row] * 3, step=pd.Timedelta(hours=1))


def m15_buy_setup(**last_overrides: float) -> pd.DataFrame:
    """Pullback ke EMA20, RSI naik melewati 40, MACD cross naik di candle terakhir."""
    rows = []
    rsis = [45, 41, 36, 37, 38, 42]
    macds = [(0.1, 0.0), (0.0, 0.05), (-0.1, 0.0), (-0.12, -0.02), (-0.08, -0.03), (0.02, -0.02)]
    for i in range(6):
        macd_v, sig = macds[i]
        rows.append({
            "open": 100.6, "high": 101.2, "low": 100.3 if i == 3 else 100.8, "close": 100.9,
            "ema_fast": 100.5, "ema_mid": 100.0, "ema_slow": 99.0, "atr": 1.0, "adx": 25,
            "rsi": rsis[i], "macd": macd_v, "macd_signal": sig, "macd_hist": macd_v - sig,
        })  # fmt: skip
    rows[-1].update(close=101.0, **last_overrides)
    return make_frame(rows)


def mirror(df: pd.DataFrame) -> pd.DataFrame:
    """Cerminkan harga di sekitar 200 → setup SELL yang setara."""
    out = df.copy()
    for col in ("open", "close", "ema_fast", "ema_mid", "ema_slow"):
        out[col] = 200 - df[col]
    out["high"], out["low"] = 200 - df["low"], 200 - df["high"]
    out["rsi"] = 100 - df["rsi"]
    for col in ("macd", "macd_signal", "macd_hist"):
        out[col] = -df[col]
    return out


def ctx(inst: Instrument, m15: pd.DataFrame, h1: int = 1, h4: int = 1, spread: float = 0.0,
        active: ActiveSignalView | None = None) -> StrategyContext:  # fmt: skip
    return StrategyContext(inst, NOW, m15, trend_frame(h1), trend_frame(h4), spread, active)


@pytest.fixture
def strategy():  # type: ignore[no-untyped-def]
    return create_strategy("trend_pullback")


def test_buy_signal_with_atr_based_sl_tp(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    decision = strategy.evaluate(ctx(xauusd, m15_buy_setup()))

    assert decision.action is Action.BUY
    assert decision.entry == 101.0
    assert decision.stop_loss == 99.5  # 1.5 × ATR
    assert decision.take_profit == 104.0  # 3 × ATR, R:R 1:2
    assert decision.details["triggers"] == 3
    assert confidence_label(decision.confidence) in {"sedang", "tinggi"}
    assert any("pullback" in r for r in decision.reasons)
    assert any("RSI" in r for r in decision.reasons)


def test_tp_widened_to_keep_min_rr_after_spread(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    decision = strategy.evaluate(ctx(xauusd, m15_buy_setup(), spread=0.5))
    # TP = 2 × (1.5 + 0.5) + 0.5 = 4.5 → R:R bersih tetap 1:2
    assert decision.take_profit == 105.5
    assert decision.details["risk_reward"] == pytest.approx(2.0)


def test_sell_is_mirror_of_buy(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    decision = strategy.evaluate(ctx(xauusd, mirror(m15_buy_setup()), h1=-1, h4=-1))
    assert decision.action is Action.SELL
    assert decision.entry == 99.0
    assert decision.stop_loss == 100.5
    assert decision.take_profit == 96.0


def test_wait_when_trends_disagree(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    decision = strategy.evaluate(ctx(xauusd, m15_buy_setup(), h1=1, h4=-1))
    assert decision.action is Action.WAIT
    assert "belum searah" in decision.reasons[0]


def test_wait_when_trend_weak(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    weak = StrategyContext(xauusd, NOW, m15_buy_setup(), trend_frame(1, adx=12),
                           trend_frame(1, adx=15), 0.0)  # fmt: skip
    decision = strategy.evaluate(weak)
    assert decision.action is Action.WAIT
    assert "tren lemah" in decision.reasons[0]


def test_wait_without_pullback(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    m15 = m15_buy_setup()
    m15["low"] = 101.5  # tidak pernah menyentuh EMA20
    decision = strategy.evaluate(ctx(xauusd, m15))
    assert decision.action is Action.WAIT
    assert "pullback ke EMA20" in decision.reasons[-1]


def test_wait_when_rsi_overbought(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    m15 = m15_buy_setup()
    m15.loc[m15.index[-2:], "rsi"] = [38, 72]
    decision = strategy.evaluate(ctx(xauusd, m15))
    assert decision.action is Action.WAIT
    assert "jenuh beli" in decision.reasons[-1]


def test_should_close_on_weak_momentum(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    m15 = m15_buy_setup()
    m15["macd_hist"] = -0.05
    m15.loc[m15.index[-1], "close"] = 100.2  # di bawah EMA20 (100.5)
    active = ActiveSignalView(1, Action.BUY, 100.9, 99.4, 103.9, m15.index[-4].to_pydatetime())
    reason = strategy.should_close(ctx(xauusd, m15, active=active), active)
    assert reason is not None and "Momentum melemah" in reason


def test_should_close_when_h1_reverses(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    m15 = m15_buy_setup()
    active = ActiveSignalView(1, Action.BUY, 100.9, 99.4, 103.9, m15.index[-4].to_pydatetime())
    reason = strategy.should_close(ctx(xauusd, m15, h1=-1, active=active), active)
    assert reason == "Tren H1 berbalik menjadi turun."


def test_no_early_close_right_after_entry(strategy, xauusd: Instrument) -> None:  # type: ignore[no-untyped-def]
    m15 = m15_buy_setup()
    active = ActiveSignalView(1, Action.BUY, 101, 99.5, 104, m15.index[-1].to_pydatetime())
    assert strategy.should_close(ctx(xauusd, m15, h1=-1, active=active), active) is None


def test_unknown_strategy_rejected() -> None:
    with pytest.raises(ValueError, match="tidak dikenal"):
        create_strategy("tidak_ada")
