"""Integrasi mesin sinyal + PostgreSQL + Redis palsu (dilewati bila DB tidak tersedia)."""

import json
from datetime import UTC, datetime, timedelta

from fakeredis import FakeAsyncRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import AnalysisConfig
from app.analysis.narrator import Narrator
from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.providers.mock import MockProvider
from app.db.models import Signal
from app.services.candle_sync import sync_candles
from app.services.signal_engine import analyze_instrument, get_latest_analysis
from tests.test_lifecycle_and_engine import BUY, SELL, StubStrategy
from tests.test_risk_filters_narrator import FakeCalendar

NOW = datetime(2026, 10, 28, 6, 0, 10, tzinfo=UTC)


async def _seed(session: AsyncSession, inst: Instrument, now: datetime) -> None:
    provider = MockProvider(clock=lambda: now)
    for tf in (Timeframe.M15, Timeframe.H1, Timeframe.H4):
        await sync_candles(session, provider, inst, tf, now)


async def test_buy_then_reversal_creates_close_and_sell(
    db_session: AsyncSession, xauusd: Instrument
) -> None:
    inst = xauusd.model_copy(update={"symbol": "TESTXAU"})
    await _seed(db_session, inst, NOW)
    redis = FakeAsyncRedis()
    common = {
        "cfg": AnalysisConfig(
            filters={"max_atr_ratio": 99, "min_atr_ratio": 0, "max_candle_atr": 99}
        ),
        "narrator": Narrator("", "m"),
        "calendar": FakeCalendar([]),
    }

    snap = await analyze_instrument(
        db_session, redis, inst, NOW, strategy=StubStrategy(BUY), **common
    )
    assert snap["action"] == "BUY" and snap["is_new_event"]
    buy = await db_session.get(Signal, snap["signal_id"])
    assert buy is not None and buy.status == "ACTIVE" and buy.reason_text == "beli"
    assert buy.entry_expires_at == buy.candle_time + timedelta(minutes=15 + 45)

    # Siklus yang sama diulang: tidak membuat sinyal ganda
    again = await analyze_instrument(
        db_session, redis, inst, NOW, strategy=StubStrategy(BUY), **common
    )
    assert not again["is_new_event"] and again["action"] == "BUY"

    later = NOW + timedelta(minutes=15)
    await _seed(db_session, inst, later)
    snap2 = await analyze_instrument(
        db_session, redis, inst, later, strategy=StubStrategy(SELL), **common
    )
    rows = (
        (
            await db_session.execute(
                select(Signal).where(Signal.symbol == "TESTXAU").order_by(Signal.id)
            )
        )
        .scalars()
        .all()
    )
    assert [r.action for r in rows] == ["BUY", "CLOSE", "SELL"]
    await db_session.refresh(rows[0])
    assert rows[0].status in {"CLOSED", "HIT_SL", "HIT_TP"}
    assert rows[1].parent_id == rows[0].id and rows[1].result_pips is not None
    assert rows[2].status == "ACTIVE"
    assert snap2["action"] == "SELL" and len(snap2["event_ids"]) == 2

    stored = await get_latest_analysis(redis, "TESTXAU")
    assert stored is not None and stored["signal_id"] == rows[2].id
    json.dumps(stored)  # bisa dikirim ke frontend


async def test_waits_when_latest_candle_missing(
    db_session: AsyncSession, xauusd: Instrument
) -> None:
    inst = xauusd.model_copy(update={"symbol": "TESTXAU2"})
    await _seed(db_session, inst, NOW)
    snap = await analyze_instrument(
        db_session,
        FakeAsyncRedis(),
        inst,
        NOW + timedelta(minutes=30),  # dua candle baru belum disinkronkan
        strategy=StubStrategy(BUY),
        narrator=Narrator("", "m"),
        calendar=FakeCalendar([]),
    )
    assert snap["action"] == "WAIT"
    assert "Menunggu data" in snap["reasons"][0]


async def test_entry_timeframe_follows_request_then_open_position(
    db_session: AsyncSession, xauusd: Instrument
) -> None:
    inst = xauusd.model_copy(update={"symbol": "TESTXAU3"})
    await _seed(db_session, inst, NOW)
    await sync_candles(db_session, MockProvider(clock=lambda: NOW), inst, Timeframe.M5, NOW)
    redis = FakeAsyncRedis()
    common = {
        "cfg": AnalysisConfig(
            filters={"max_atr_ratio": 99, "min_atr_ratio": 0, "max_candle_atr": 99}
        ),
        "narrator": Narrator("", "m"),
        "calendar": FakeCalendar([]),
    }

    snap = await analyze_instrument(
        db_session, redis, inst, NOW, strategy=StubStrategy(BUY), timeframe=Timeframe.M5, **common
    )
    assert snap["timeframe"] == "M5" and snap["action"] == "BUY"
    buy = await db_session.get(Signal, snap["signal_id"])
    assert buy is not None and buy.timeframe == "M5"
    assert buy.candle_time == datetime(2026, 10, 28, 5, 55, tzinfo=UTC)
    # entry_valid_minutes 45 (M15) diskalakan → 15 menit untuk M5
    assert buy.entry_expires_at == buy.candle_time + timedelta(minutes=5 + 15)

    # Posisi aktif tetap dipantau di M5 walau diminta H1
    again = await analyze_instrument(
        db_session, redis, inst, NOW, strategy=StubStrategy(BUY), timeframe=Timeframe.H1, **common
    )
    assert again["timeframe"] == "M5" and again["action"] == "BUY"
