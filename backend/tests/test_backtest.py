from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.analysis.config import AnalysisConfig
from app.analysis.replay import ReplayTrade
from app.backtest.metrics import TradeResult, compute_metrics, equity_curve
from app.backtest.runner import BacktestRequest, InstrumentData, compute_backtest, to_trade_results
from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.providers.mock import MockProvider

T0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)  # Senin


def trade(pips: float, risk: float = 10.0, day: int = 0, status: str | None = None) -> TradeResult:
    t = T0 + timedelta(days=day)
    return TradeResult(
        symbol="EURUSD",
        action="BUY",
        entry_time=t,
        exit_time=t + timedelta(hours=1),
        status=status or ("HIT_TP" if pips > 0 else "HIT_SL"),
        result_pips=pips,
        risk_pips=risk,
        planned_rr=2.0,
    )


def test_metrics_basic_numbers() -> None:
    # +2R, −1R, +2R, −1R  → total +2R, win rate 50%, PF 4/2 = 2.0
    m = compute_metrics([trade(20, day=0), trade(-10, day=1), trade(20, day=2), trade(-10, day=3)])
    assert (m.trades, m.wins, m.losses) == (4, 2, 2)
    assert m.win_rate == 50.0
    assert m.total_r == 2.0
    assert m.expectancy_r == 0.5
    assert m.profit_factor == 2.0
    assert (m.win_pips, m.loss_pips, m.win_r, m.loss_r) == (40.0, -20.0, 4.0, -2.0)
    assert m.avg_rr_realized == 2.0
    assert m.avg_rr_planned == 2.0
    assert m.net_pips == 20.0
    assert m.by_status == {"HIT_TP": 2, "HIT_SL": 2}


def test_max_drawdown_r_and_pct() -> None:
    # +1R lalu −1R, −1R, −1R → puncak +1R, dasar −2R → DD 3R
    m = compute_metrics([trade(10, day=0), trade(-10, day=1), trade(-10, day=2), trade(-10, day=3)])
    assert m.max_drawdown_r == 3.0
    # modal: 101 → 99.99 → 98.99 → 98.00 ; DD dari 101 ≈ 2.97%
    assert m.max_drawdown_pct == pytest.approx(2.97, abs=0.01)
    assert m.return_pct == pytest.approx(-2.0, abs=0.05)


def test_no_losses_profit_factor_undefined_and_empty() -> None:
    assert compute_metrics([trade(10)]).profit_factor is None
    empty = compute_metrics([])
    assert empty.trades == 0 and empty.win_rate is None and empty.sharpe is None


def test_sharpe_positive_for_consistent_gains() -> None:
    trades = [trade(10 if i % 3 else -5, day=i) for i in range(30)]
    m = compute_metrics(trades)
    assert m.sharpe is not None and m.sharpe > 0


def test_equity_curve_unique_times() -> None:
    same = [trade(10), trade(-10)]  # waktu keluar sama
    curve = equity_curve(same)
    assert len(curve) == 1


def test_trade_conversion_applies_slippage(xauusd: Instrument) -> None:
    raw = ReplayTrade(
        action="BUY", entry_time=T0, entry=4000.0, stop_loss=3997.5, take_profit=4005.0,
        confidence=0.8, exit_time=T0 + timedelta(hours=1), exit_price=4005.0,
        status="HIT_TP", result_pips=47.5,
    )  # fmt: skip
    [t] = to_trade_results([raw], xauusd, spread_pips=2.5, slippage_pips=1.0)
    assert t.result_pips == 45.5  # 47.5 − 2 × 1.0
    assert t.risk_pips == pytest.approx(25 + 2.5 + 1.0)
    assert t.planned_rr == pytest.approx((50 - 2.5) / 27.5, abs=0.01)
    # posisi yang masih terbuka di akhir periode diabaikan
    open_trade = ReplayTrade("SELL", T0, 4000.0, 4002.5, 3995.0, 0.6)
    assert to_trade_results([open_trade], xauusd, 2.5, 1.0) == []


def _frame(candles: list) -> pd.DataFrame:  # type: ignore[type-arg]
    return pd.DataFrame(
        {k: [getattr(c, k) for c in candles] for k in ("open", "high", "low", "close")},
        index=pd.DatetimeIndex([c.open_time for c in candles]),
    )


async def test_compute_backtest_structure(eurusd: Instrument) -> None:
    end = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    provider = MockProvider(clock=lambda: end)
    frames = {
        tf: _frame(await provider.fetch_candles(eurusd, tf, limit=5000))
        for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4)
    }
    start = frames[Timeframe.M15].index[300].to_pydatetime()
    req = BacktestRequest(days=40, windows=3)
    data = InstrumentData(eurusd, frames, spread_pips=0.8, slippage_pips=0.2)

    specs = {"EURUSD": ("trend_pullback", {})}
    summary = compute_backtest([data], specs, AnalysisConfig(), start, end, req)

    res = summary["instruments"]["EURUSD"]
    assert len(res["windows"]) == 3
    assert sum(w["trades"] for w in res["windows"]) == res["all"]["trades"]
    assert res["in_sample"]["trades"] + res["out_of_sample"]["trades"] == res["all"]["trades"]
    assert summary["portfolio"]["all"]["trades"] == res["all"]["trades"]
    assert res["costs"] == {"spread_pips": 0.8, "slippage_pips": 0.2}
    assert all(t["status"] in {"HIT_TP", "HIT_SL", "CLOSED"} for t in res["trades"])
