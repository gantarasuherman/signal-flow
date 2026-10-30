from datetime import UTC, datetime, timedelta

import pandas as pd

from app.analysis.replay import ReplayTrade
from app.core.instruments import Instrument
from app.services.signal_exit import ExitProfile, best_close, exit_profile


def frame(closes: list[float], start: datetime) -> pd.DataFrame:
    idx = pd.DatetimeIndex([start + timedelta(minutes=15 * i) for i in range(len(closes))])
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
        },
        index=idx,
    )


def test_exit_profile_respects_stop_loss(xauusd: Instrument) -> None:
    start = datetime(2027, 1, 5, 8, 0, tzinfo=UTC)
    # BUY di 4000: naik 3 candle lalu jatuh menembus SL 3995 di candle ke-4
    df = frame([4000, 4001, 4002, 4003, 3990, 4010, 4010], start)
    trade = ReplayTrade("BUY", start, 4000.0, 3995.0, 4100.0, 0.5, result_pips=-50.0)
    pip = xauusd.pip_size
    p = exit_profile([trade], df, xauusd, 0.0, 0.0, max_hold=6)
    assert p.samples == 1 and p.strategy_pips == -50.0
    assert [round(x * pip, 2) for x in p.net[:3]] == [1.0, 2.0, 3.0]
    # Setelah SL tersentuh, menahan lebih lama tidak bisa memperbaiki hasil
    assert all(round(x * pip, 2) == -5.0 for x in p.net[3:])
    assert p.wins == [1, 1, 1, 0, 0, 0]


def test_best_close_needs_enough_trades() -> None:
    few = ExitProfile(net=[5.0, 10.0], wins=[3, 4], samples=5, strategy_pips=2.0)
    assert best_close(few) is None
    many = ExitProfile(
        net=[5.0, 10.0, 9.5, -2.0], wins=[20, 25, 24, 10], samples=40, strategy_pips=2.0
    )
    plan = best_close(many)
    assert plan is not None and plan.hold == 2 and plan.pips == 10.0
    assert best_close(None) is None


def test_exit_profile_is_json_serializable(xauusd: Instrument) -> None:
    import json
    from dataclasses import asdict

    start = datetime(2027, 1, 5, 8, 0, tzinfo=UTC)
    df = frame([4000, 4001, 4002, 4003], start)
    trade = ReplayTrade("BUY", start, 4000.0, 3995.0, 4100.0, 0.5, result_pips=10.0)
    json.dumps(asdict(exit_profile([trade], df, xauusd, 0.0, 0.0, max_hold=3)))
