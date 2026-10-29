from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.analysis.config import AnalysisConfig
from app.backtest.validation import is_validated, select_candidate, validation_reason
from app.core.instruments import Instrument
from app.strategies import Action, StrategyContext, create_strategy
from tests.test_strategy import trend_frame

DAY = datetime(2026, 10, 28, tzinfo=UTC)  # Rabu


def m15_day(rows_until: datetime, closes: dict[datetime, float] | None = None) -> pd.DataFrame:
    """Candle M15 dari 00:00 UTC hari ini sampai `rows_until`; rentang Asia 100–102."""
    index, rows = [], []
    t = DAY
    while t <= rows_until:
        close = (closes or {}).get(t, 101.0)
        rows.append({
            "open": 101.0, "high": max(102.0, close) if t.hour < 7 else max(101.5, close),
            "low": min(100.0, close) if t.hour < 7 else min(100.5, close), "close": close,
            "ema_fast": 101.0, "ema_mid": 100.5, "ema_slow": 100.0, "atr": 1.0, "adx": 25,
            "rsi": 55, "macd": 0, "macd_signal": 0, "macd_hist": 0,
        })  # fmt: skip
        index.append(t)
        t += timedelta(minutes=15)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(index))


def ctx(inst: Instrument, m15: pd.DataFrame, h4: int = 1, h1: int = 1) -> StrategyContext:
    now = m15.index[-1].to_pydatetime() + timedelta(minutes=15)
    return StrategyContext(inst, now, m15, trend_frame(h1), trend_frame(h4), 0.0)


# ---------- session_breakout ----------


def test_session_breakout_buy_on_first_close_above_range(xauusd: Instrument) -> None:
    t = DAY + timedelta(hours=8)
    m15 = m15_day(t, {t: 102.5})  # rentang 100–102, buffer 0.1 → tembus di 102.5
    d = create_strategy("session_breakout").evaluate(ctx(xauusd, m15))
    assert d.action is Action.BUY
    assert d.entry == 102.5
    # SL di tengah rentang (101) → jarak 1.5; TP R:R 2 → +3.0
    assert (d.stop_loss, d.take_profit) == (101.0, 105.5)


def test_session_breakout_only_first_break_of_day(xauusd: Instrument) -> None:
    t = DAY + timedelta(hours=9)
    early = DAY + timedelta(hours=8)
    m15 = m15_day(t, {early: 99.5, t: 102.5})  # sudah tembus ke bawah lebih awal
    d = create_strategy("session_breakout").evaluate(ctx(xauusd, m15))
    assert d.action is Action.WAIT
    assert "lebih awal" in d.reasons[0]


def test_session_breakout_respects_h4_trend(xauusd: Instrument) -> None:
    t = DAY + timedelta(hours=8)
    m15 = m15_day(t, {t: 102.5})
    assert (
        create_strategy("session_breakout").evaluate(ctx(xauusd, m15, h4=-1)).action is Action.WAIT
    )
    no_filter = create_strategy("session_breakout", {"trend_filter": "none"})
    assert no_filter.evaluate(ctx(xauusd, m15, h4=-1)).action is Action.BUY


def test_session_breakout_outside_window(xauusd: Instrument) -> None:
    m15 = m15_day(DAY + timedelta(hours=13), {DAY + timedelta(hours=13): 103.0})
    d = create_strategy("session_breakout").evaluate(ctx(xauusd, m15))
    assert d.action is Action.WAIT and "WIB" in d.reasons[0]


# ---------- donchian_breakout ----------


def donchian_frame(last_close: float, adx: float = 25) -> pd.DataFrame:
    end = DAY + timedelta(hours=10)
    index = pd.DatetimeIndex([end - timedelta(minutes=15 * (25 - i)) for i in range(26)])
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "ema_fast": 100, "atr": 1.0, "adx": adx}
        for _ in range(26)
    ]
    rows[-1].update(close=last_close, high=max(101, last_close), adx=adx)
    return pd.DataFrame(rows, index=index)


def test_donchian_buy_on_channel_break(xauusd: Instrument) -> None:
    d = create_strategy("donchian_breakout").evaluate(ctx(xauusd, donchian_frame(101.5)))
    assert d.action is Action.BUY
    assert (d.entry, d.stop_loss, d.take_profit) == (101.5, 99.5, 105.5)


def test_donchian_needs_momentum_and_session(xauusd: Instrument) -> None:
    s = create_strategy("donchian_breakout")
    assert s.evaluate(ctx(xauusd, donchian_frame(101.5, adx=12))).action is Action.WAIT
    late = donchian_frame(101.5)
    late.index = late.index + timedelta(hours=10)  # 20:00 UTC, di luar sesi
    d = s.evaluate(ctx(xauusd, late))
    assert d.action is Action.WAIT and "Di luar jam trading" in d.reasons[0]


# ---------- trend_pullback: parameter baru ----------


def test_pullback_session_filter_and_no_early_close(xauusd: Instrument) -> None:
    from tests.test_strategy import m15_buy_setup

    m15 = m15_buy_setup()  # candle terakhir 06:00 UTC → ctx.now 06:15 UTC
    s = create_strategy("trend_pullback", {"entry_hours_utc": list(range(7, 17))})
    now = m15.index[-1].to_pydatetime() + timedelta(minutes=15)
    decision = s.evaluate(StrategyContext(xauusd, now, m15, trend_frame(1), trend_frame(1), 0.0))
    assert decision.action is Action.WAIT

    no_close = create_strategy("trend_pullback", {"early_close": False})
    from app.strategies import ActiveSignalView

    active = ActiveSignalView(1, Action.BUY, 100.9, 99.4, 103.9, m15.index[-4].to_pydatetime())
    c = StrategyContext(xauusd, now, m15, trend_frame(-1), trend_frame(1), 0.0, active)
    assert no_close.should_close(c, active) is None


# ---------- konfigurasi & validasi ----------


def test_spec_for_merges_defaults_and_overrides() -> None:
    cfg = AnalysisConfig.model_validate(
        {
            "active": "trend_pullback",
            "strategies": {"trend_pullback": {"sl_atr": 1.5}, "session_breakout": {"rr": 2.0}},
            "instruments": {"XAUUSD": {"strategy": "session_breakout", "params": {"rr": 3.0}}},
        }
    )
    assert cfg.spec_for("EURUSD") == ("trend_pullback", {"sl_atr": 1.5})
    assert cfg.spec_for("xauusd") == ("session_breakout", {"rr": 3.0})


def _m(trades: int, pf: float | None, exp: float | None) -> dict:  # type: ignore[type-arg]
    return {"trades": trades, "profit_factor": pf, "expectancy_r": exp}


@pytest.mark.parametrize(
    ("oos", "ok"),
    [
        (_m(30, 1.3, 0.1), True),
        (_m(10, 2.0, 0.5), False),  # trade terlalu sedikit
        (_m(30, 1.05, 0.02), False),  # PF di bawah 1.1
        (_m(30, None, None), False),
    ],
)
def test_validation_rule(oos: dict, ok: bool) -> None:  # type: ignore[type-arg]
    assert is_validated(oos) is ok
    assert validation_reason(oos)


def test_selection_uses_in_sample_only() -> None:
    results = [
        {"label": "a", "in_sample": _m(50, 1.2, 0.10), "out_of_sample": _m(30, 2.0, 0.5)},
        {"label": "b", "in_sample": _m(60, 1.5, 0.20), "out_of_sample": _m(30, 0.5, -0.3)},
        {"label": "c", "in_sample": _m(10, 3.0, 0.90), "out_of_sample": _m(30, 3.0, 0.9)},
    ]
    # 'c' trade IS terlalu sedikit; 'b' terbaik di IS walau OOS-nya buruk → tetap 'b'
    assert select_candidate(results)["label"] == "b"


def test_in_sample_loss_fails_validation() -> None:
    good_oos = _m(30, 1.3, 0.1)
    assert is_validated(good_oos, _m(60, 1.05, 0.02))
    assert not is_validated(good_oos, _m(60, 0.83, -0.1))
    assert "in-sample" in validation_reason(good_oos, _m(60, 0.83, -0.1))


def test_disabled_strategy_always_waits(xauusd: Instrument) -> None:
    m15 = m15_day(DAY + timedelta(hours=8), {DAY + timedelta(hours=8): 102.5})
    d = create_strategy("disabled").evaluate(ctx(xauusd, m15))
    assert d.action is Action.WAIT and "dinonaktifkan" in d.reasons[0]
