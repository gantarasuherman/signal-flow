from datetime import UTC, datetime, timedelta

import pytest

from app.core.instruments import Instrument
from app.db.models import Signal
from app.services.risk_prefs import RiskPrefs
from app.services.views import EntryState, PriceInfo, build_signal_view, entry_state

CANDLE = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)
NOW = CANDLE + timedelta(minutes=20)


def buy_signal(**overrides: object) -> Signal:
    values: dict[str, object] = {
        "id": 7,
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "strategy": "trend_pullback",
        "action": "BUY",
        "candle_time": CANDLE,
        "created_at": CANDLE + timedelta(minutes=15, seconds=12),
        "entry": 4000.0,
        "stop_loss": 3997.5,
        "take_profit": 4005.0,
        "risk_reward": 2.0,
        "spread_pips": 2.5,
        "confidence": 0.8,
        "confidence_label": "tinggi",
        "entry_expires_at": CANDLE + timedelta(minutes=60),
        "reasons": ["Tren naik."],
        "reason_text": "Tren naik.",
        "status": "ACTIVE",
    }
    values.update(overrides)
    return Signal(**values)


def price(value: float) -> PriceInfo:
    return PriceInfo(price=value, source="live", updated_at=NOW)


@pytest.mark.parametrize(
    ("now", "current", "expected", "distance"),
    [
        (NOW, 4001.0, EntryState.VALID, 10.0),
        (NOW, 3999.0, EntryState.VALID, -10.0),
        (NOW, 4001.6, EntryState.EXPIRED_DISTANCE, 16.0),  # batas XAUUSD 15 pip
        (CANDLE + timedelta(minutes=61), 4000.2, EntryState.EXPIRED_TIME, 2.0),
        (NOW, None, EntryState.VALID, None),
    ],
)
def test_entry_state(
    xauusd: Instrument,
    now: datetime,
    current: float | None,
    expected: EntryState,
    distance: float | None,
) -> None:
    state, dist = entry_state(buy_signal(), now, current, xauusd.signal_validity_pips, 0.1)
    assert state is expected
    assert dist == distance


def test_sell_distance_sign(xauusd: Instrument) -> None:
    sell = buy_signal(action="SELL", stop_loss=4002.5, take_profit=3995.0)
    _, dist = entry_state(sell, NOW, 3999.0, 15, 0.1)
    assert dist == 10.0  # harga turun = searah sinyal SELL


def test_view_applies_offset_and_computes_pips_and_lot(xauusd: Instrument) -> None:
    view = build_signal_view(
        buy_signal(),
        xauusd,
        offset=1.25,
        now=NOW,
        price=price(4000.5),
        prefs=RiskPrefs(capital=1000, risk_percent=1),
    )
    assert (view.entry, view.stop_loss, view.take_profit) == (4001.25, 3998.75, 4006.25)
    assert (view.sl_pips, view.tp_pips) == (25.0, 50.0)
    assert view.current_price == 4001.75
    assert view.signal_time == CANDLE + timedelta(minutes=15)
    assert view.status == "ACTIVE" and view.status_label == "aktif"
    assert view.entry_state is EntryState.VALID
    assert view.risk_amount == 10.0
    assert view.suggested_lot == 0.04  # $10 / (25 pip × $10) = 0.04


def test_view_marks_expired_but_keeps_tracking(xauusd: Instrument) -> None:
    view = build_signal_view(
        buy_signal(), xauusd, offset=0, now=NOW, price=price(4003.0), prefs=RiskPrefs()
    )
    assert view.status == "EXPIRED"
    assert "jangan masuk" in view.entry_state_label
    assert view.suggested_lot is None  # modal belum diisi


def test_view_for_closed_and_close_event(xauusd: Instrument) -> None:
    hit = buy_signal(status="HIT_TP", close_price=4005.0, result_pips=47.5, closed_at=NOW)
    view = build_signal_view(hit, xauusd, offset=0, now=NOW, price=None, prefs=RiskPrefs())
    assert view.status_label == "kena TP" and view.entry_state is EntryState.CLOSED

    close = buy_signal(id=8, action="CLOSE", status=None, parent_id=7, close_reason="TP")
    view = build_signal_view(
        close, xauusd, offset=0, now=NOW, price=None, prefs=RiskPrefs(), closes_action="BUY"
    )
    assert view.action == "CLOSE" and view.closes_action == "BUY"
    assert view.status_label == "ditutup"
    assert view.suggested_lot is None


def test_view_shows_trailing_stop_adjusted_to_broker(xauusd: Instrument) -> None:
    view = build_signal_view(
        buy_signal(),
        xauusd,
        offset=1.25,
        now=NOW,
        price=price(4003.0),
        prefs=RiskPrefs(),
        trailing_stop=4002.0,
        take_profit_active=False,
    )
    assert view.trailing_stop == 4003.25 and view.stop_loss == 3998.75
    assert not view.take_profit_active
