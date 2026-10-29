from datetime import UTC, datetime
from typing import ClassVar

import pandas as pd
import pytest
from pydantic import BaseModel

from app.analysis.engine import step
from app.analysis.lifecycle import (
    SignalStatus,
    TrailingStopConfig,
    check_price_exit,
    result_pips,
    trailing_stops,
)
from app.core.instruments import Instrument
from app.strategies import Action, ActiveSignalView, Decision, Strategy, StrategyContext
from tests.conftest import make_frame

T = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)


def candles(*hl: tuple[float, float], close: float = 100.0) -> pd.DataFrame:
    rows = [{"open": close, "high": h, "low": lo, "close": close} for h, lo in hl]
    return make_frame(rows)


def test_buy_hits_tp() -> None:
    hit = check_price_exit(Action.BUY, 99.0, 102.0, candles((101, 99.5), (102.1, 100)), 0.0)
    assert hit is not None and hit.status is SignalStatus.HIT_TP and hit.price == 102.0


def test_same_candle_sl_and_tp_assumes_sl() -> None:
    hit = check_price_exit(Action.BUY, 99.0, 102.0, candles((102.5, 98.5)), 0.0)
    assert hit is not None and hit.status is SignalStatus.HIT_SL


def test_sell_sl_uses_ask_price() -> None:
    # SELL SL 101; high BID 100.8 + spread 0.3 = ASK 101.1 → SL kena
    hit = check_price_exit(Action.SELL, 101.0, 98.0, candles((100.8, 99.5)), 0.3)
    assert hit is not None and hit.status is SignalStatus.HIT_SL
    assert check_price_exit(Action.SELL, 101.0, 98.0, candles((100.8, 99.5)), 0.1) is None


TRAIL = TrailingStopConfig(enabled=True, activate_r=1.0, distance_r=1.0, take_profit=False)


def test_buy_trailing_stop_locks_profit_from_best_high() -> None:
    # entry 100, SL 99 (R = 1). High 101 → stop ke 100 (impas); high 103 → stop 102.
    rows = candles((101.0, 99.5), (103.0, 101.5), (102.8, 101.9))
    hit = check_price_exit(Action.BUY, 99.0, 102.0, rows, 0.0, entry=100.0, trailing=TRAIL)
    assert hit is not None and hit.trailing and hit.status is SignalStatus.CLOSED
    assert hit.price == 102.0  # TP 102 dilepas → untung dibiarkan berjalan


def test_sell_trailing_stop_mirrors_buy_with_ask_prices() -> None:
    # SELL entry 100 (BID), SL 101 (ASK), spread 0.2 → low 98.8 = ASK 99.0 = untung 1R
    rows = candles((100.1, 98.8), (99.4, 97.8), (99.3, 98.0))
    hit = check_price_exit(Action.SELL, 101.0, 97.0, rows, 0.2, entry=100.0, trailing=TRAIL)
    assert hit is not None and hit.trailing
    assert hit.price == pytest.approx(99.0)  # ASK terbaik 98.0 + 1R


def test_trailing_uses_only_previous_candles_and_keeps_plain_sl() -> None:
    # Candle yang sama naik 1R lalu turun ke entry: stop belum pindah → tidak tertutup
    rows = candles((101.5, 99.6))
    assert check_price_exit(Action.BUY, 99.0, 105.0, rows, 0.0, entry=100.0, trailing=TRAIL) is None
    # Belum pernah untung 1R → SL awal tetap berlaku sebagai HIT_SL biasa
    hit = check_price_exit(
        Action.BUY,
        99.0,
        105.0,
        candles((100.5, 99.5), (100.2, 98.9)),
        0.0,
        entry=100.0,
        trailing=TRAIL,
    )
    assert hit is not None and hit.status is SignalStatus.HIT_SL and not hit.trailing


def test_trailing_stops_last_value_is_current_stop() -> None:
    rows = candles((101.0, 99.5), (103.0, 101.5))
    stops = trailing_stops(Action.BUY, 99.0, 100.0, rows, 0.0, TRAIL)
    assert stops == [99.0, 100.0, 102.0]  # SL awal → impas → ikut high 103 − 1R


def test_trailing_breakeven_covers_spread() -> None:
    # BUY dibayar di ASK 100.5; untung 1R baru saat BID 101.5 → stop pertama = 100.5
    rows = candles((101.4, 100.2), (101.5, 100.6), (101.0, 100.4))
    hit = check_price_exit(Action.BUY, 99.0, 110.0, rows, 0.5, entry=100.0, trailing=TRAIL)
    assert hit is not None and hit.price == pytest.approx(100.5)
    assert result_pips(Action.BUY, 100.0, hit.price, 0.5, 0.1) == 0.0


def test_result_pips_net_of_spread() -> None:
    assert result_pips(Action.BUY, 100.0, 103.0, 0.25, 0.1) == 27.5
    assert result_pips(Action.SELL, 100.0, 98.5, 0.25, 0.1) == 15.0
    assert result_pips(Action.BUY, 100.0, 98.5, 0.25, 0.1) == -17.5


class _Params(BaseModel):
    pass


class StubStrategy(Strategy):
    """Strategi palsu: mengembalikan keputusan yang ditentukan test."""

    name = "stub"
    Params: ClassVar[type[BaseModel]] = _Params
    min_bars = 1

    def __init__(self, decision: Decision, close_reason: str | None = None) -> None:
        super().__init__()
        self.decision = decision
        self.close_reason = close_reason

    def evaluate(self, ctx: StrategyContext) -> Decision:
        return self.decision

    def should_close(self, ctx: StrategyContext, active: ActiveSignalView) -> str | None:
        return self.close_reason


BUY = Decision(Action.BUY, 100.0, 98.5, 103.0, 0.8, ["beli"])
SELL = Decision(Action.SELL, 100.0, 101.5, 97.0, 0.8, ["jual"])
WAIT = Decision(Action.WAIT, reasons=["tunggu"])


def make_ctx(
    inst: Instrument, m15: pd.DataFrame, active: ActiveSignalView | None
) -> StrategyContext:
    return StrategyContext(inst, T, m15, m15, m15, 0.0, active)


def active_buy(at: datetime) -> ActiveSignalView:
    return ActiveSignalView(1, Action.BUY, 100.0, 98.5, 103.0, at)


def test_new_entry_when_no_active(xauusd: Instrument) -> None:
    m15 = candles((100.5, 99.5))
    result = step(StubStrategy(BUY), make_ctx(xauusd, m15, None), [], 32)
    assert result.new_entry is BUY and result.exit is None


def test_filter_blocks_entry(xauusd: Instrument) -> None:
    m15 = candles((100.5, 99.5))
    result = step(StubStrategy(BUY), make_ctx(xauusd, m15, None), ["Volatilitas ekstrem"], 32)
    assert result.new_entry is None
    assert result.decision.action is Action.WAIT
    assert "ditahan" in result.decision.reasons[-1]


def test_active_hits_tp_then_can_reenter(xauusd: Instrument) -> None:
    m15 = candles((100.5, 99.5), (103.2, 100.5))
    active = active_buy(m15.index[0].to_pydatetime())
    result = step(StubStrategy(BUY), make_ctx(xauusd, m15, active), [], 32)
    assert result.exit is not None and result.exit.status is SignalStatus.HIT_TP
    assert result.exit.result_pips == 30.0
    assert result.new_entry is BUY


def test_reversal_closes_and_opens_opposite(xauusd: Instrument) -> None:
    m15 = candles((100.5, 99.5), (100.4, 99.6), close=99.8)
    active = active_buy(m15.index[0].to_pydatetime())
    result = step(StubStrategy(SELL), make_ctx(xauusd, m15, active), [], 32)
    assert result.exit is not None and result.exit.status is SignalStatus.CLOSED
    assert "berbalik arah menjadi SELL" in result.exit.reason
    assert result.exit.result_pips == pytest.approx(-2.0)
    assert result.new_entry is SELL


def test_same_direction_keeps_active(xauusd: Instrument) -> None:
    m15 = candles((100.5, 99.5), (100.6, 99.6))
    active = active_buy(m15.index[0].to_pydatetime())
    result = step(StubStrategy(BUY), make_ctx(xauusd, m15, active), [], 32)
    assert result.exit is None and result.new_entry is None
    assert result.still_active == active


def test_momentum_close_from_strategy(xauusd: Instrument) -> None:
    m15 = candles((100.5, 99.5), (100.6, 99.6))
    active = active_buy(m15.index[0].to_pydatetime())
    result = step(StubStrategy(WAIT, "Momentum melemah"), make_ctx(xauusd, m15, active), [], 32)
    assert result.exit is not None and result.exit.reason == "Momentum melemah"


def test_max_hold_closes(xauusd: Instrument) -> None:
    m15 = candles(*[(100.5, 99.5)] * 5)
    active = active_buy(m15.index[0].to_pydatetime())
    result = step(StubStrategy(WAIT), make_ctx(xauusd, m15, active), [], max_hold_candles=4)
    assert result.exit is not None and "Batas waktu" in result.exit.reason
