"""Menjalankan analisis untuk satu instrumen: baca candle, evaluasi strategi, simpan event
sinyal, simpan ringkasan analisis terbaru ke Redis, dan publikasikan event."""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import (
    AnalysisConfig,
    get_analysis_config,
    get_news_calendar,
    get_strategy_for,
)
from app.analysis.engine import ExitEvent, step
from app.analysis.filters import run_filters
from app.analysis.indicators import compute_indicators
from app.analysis.narrator import Narrator, get_narrator, rule_based_text
from app.analysis.news import NewsCalendar
from app.analysis.risk import price_to_pips
from app.core.instruments import Instrument
from app.core.market_hours import is_market_open, last_expected_candle_open
from app.core.timeframes import Timeframe, next_candle_close
from app.db.models import Candle, Signal
from app.repositories import candles as candles_repo
from app.repositories import instrument_settings as settings_repo
from app.repositories import signals as signals_repo
from app.strategies import (
    Action,
    ActiveSignalView,
    Decision,
    Strategy,
    StrategyContext,
    confidence_label,
)

logger = logging.getLogger(__name__)

ANALYSIS_KEY = "analysis:latest:{symbol}"  # sumber "rule"; sumber "ai" diberi akhiran ":ai"
EVENTS_CHANNEL = "signals:events"
ANALYSIS_CHANNEL = "analysis:updates"
FRAME_LIMIT = {
    Timeframe.M1: 400,
    Timeframe.M5: 400,
    Timeframe.M15: 400,
    Timeframe.H1: 300,
    Timeframe.H4: 300,
}


def candles_to_frame(rows: list[Candle]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    df = pd.DataFrame(
        {
            "open": [r.open for r in rows],
            "high": [r.high for r in rows],
            "low": [r.low for r in rows],
            "close": [r.close for r in rows],
        },
        index=pd.DatetimeIndex([r.open_time for r in rows], name="open_time"),
    )
    df.index = df.index.tz_convert(UTC)
    return df


def to_view(signal: Signal) -> ActiveSignalView:
    assert signal.entry is not None and signal.stop_loss is not None
    assert signal.take_profit is not None
    return ActiveSignalView(
        id=signal.id,
        action=Action(signal.action),
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        candle_time=signal.candle_time,
    )


def analysis_timeframes(timeframe: Timeframe) -> set[Timeframe]:
    """Frame entry + konteks tren H1 & H4."""
    return {timeframe, Timeframe.H1, Timeframe.H4}


async def resolve_timeframe(
    session: AsyncSession, symbol: str, source: str, requested: Timeframe
) -> Timeframe:
    """Posisi aktif selalu dipantau di timeframe tempat ia dibuka."""
    active = await signals_repo.get_active_for_symbol(session, symbol, source=source)
    return Timeframe(active.timeframe) if active else requested


async def _load_frames(
    session: AsyncSession, symbol: str, timeframes: set[Timeframe]
) -> dict[Timeframe, pd.DataFrame]:
    frames = {}
    for tf in timeframes:
        rows = await candles_repo.get_candles(session, symbol, tf, limit=FRAME_LIMIT[tf])
        frames[tf] = candles_to_frame(rows)
    return frames


def _signal_facts(
    instrument: Instrument, decision: Decision, timeframe: Timeframe
) -> dict[str, Any]:
    assert decision.entry is not None and decision.stop_loss is not None
    assert decision.take_profit is not None
    return {
        "instrumen": f"{instrument.symbol} ({instrument.name})",
        "aksi": str(decision.action),
        "timeframe": f"{timeframe} (konfirmasi tren H1 & H4)",
        "entry": decision.entry,
        "stop_loss": decision.stop_loss,
        "take_profit": decision.take_profit,
        "jarak_sl_pip": price_to_pips(decision.entry - decision.stop_loss, instrument),
        "jarak_tp_pip": price_to_pips(decision.take_profit - decision.entry, instrument),
        "keyakinan": confidence_label(decision.confidence),
    }


def analysis_key(symbol: str, source: str = "rule") -> str:
    key = ANALYSIS_KEY.format(symbol=symbol)
    return key if source == "rule" else f"{key}:{source}"


async def _describe(
    narrator: Narrator, narrate: bool, facts: dict[str, Any], reasons: list[str]
) -> str:
    return await narrator.describe(facts, reasons) if narrate else rule_based_text(reasons)


async def _persist_exit(
    session: AsyncSession,
    active: Signal,
    exit_event: ExitEvent,
    narrator: Narrator,
    instrument: Instrument,
    narrate: bool = True,
) -> Signal:
    active.status = exit_event.status.value
    active.closed_at = exit_event.time
    active.close_price = instrument.round_price(exit_event.price)
    active.close_reason = exit_event.reason
    active.result_pips = exit_event.result_pips

    outcome = "untung" if exit_event.result_pips > 0 else "rugi"
    reasons = [
        f"Tutup posisi {active.action} {instrument.symbol}: {exit_event.reason}",
        f"Hasil {exit_event.result_pips:+.1f} pip ({outcome}) bila masuk di harga entry sinyal.",
    ]
    facts = {
        "instrumen": instrument.symbol,
        "aksi": "CLOSE",
        "posisi_yang_ditutup": active.action,
        "alasan_tutup": exit_event.reason,
        "hasil_pip": exit_event.result_pips,
    }
    close = Signal(
        symbol=active.symbol,
        timeframe=active.timeframe,
        strategy=active.strategy,
        action=Action.CLOSE.value,
        candle_time=exit_event.time,
        entry=active.entry,
        stop_loss=active.stop_loss,
        take_profit=active.take_profit,
        spread_pips=active.spread_pips,
        parent_id=active.id,
        close_price=active.close_price,
        close_reason=exit_event.reason,
        result_pips=exit_event.result_pips,
        reasons=reasons,
        reason_text=await _describe(narrator, narrate, facts, reasons),
        details={"closed_status": exit_event.status.value},
    )
    session.add(close)
    return close


async def analyze_instrument(
    session: AsyncSession,
    redis: Redis,
    instrument: Instrument,
    now: datetime,
    *,
    strategy: Strategy | None = None,
    cfg: AnalysisConfig | None = None,
    narrator: Narrator | None = None,
    calendar: NewsCalendar | None = None,
    timeframe: Timeframe = Timeframe.M15,
) -> dict[str, Any]:
    """`timeframe` = frame entry yang diminta; posisi aktif tetap memakai timeframe-nya."""
    strategy = strategy or get_strategy_for(instrument.symbol)
    cfg = cfg or get_analysis_config()
    narrator = narrator or get_narrator()
    calendar = calendar or get_news_calendar()
    symbol = instrument.symbol

    source = strategy.source
    # Sinyal aktif dari strategi mana pun dengan sumber yang sama tetap dipantau
    # (mis. setelah strategi aturan diganti); sinyal AI & aturan dilacak terpisah.
    active_row = await signals_repo.get_active_for_symbol(session, symbol, source=source)
    if active_row:
        timeframe = Timeframe(active_row.timeframe)
    snapshot: dict[str, Any] = {
        "symbol": symbol,
        "strategy": strategy.name,
        "source": source,
        "analyzed_at": now.isoformat(),
        "timeframe": timeframe.value,
        "next_candle_close": next_candle_close(now, timeframe).isoformat(),
        "market_open": is_market_open(instrument.asset_class, now),
        "action": active_row.action if active_row else Action.WAIT.value,
        "is_new_event": False,
        "signal_id": active_row.id if active_row else None,
        "event_ids": [],
        "reasons": [],
        "filters": [],
        "details": {},
        "candle_time": None,
        "last_close": None,
    }

    async def finish(reasons: list[str]) -> dict[str, Any]:
        snapshot["reasons"] = reasons
        await redis.set(analysis_key(symbol, source), json.dumps(snapshot, default=str))
        await redis.publish(ANALYSIS_CHANNEL, json.dumps({"symbol": symbol, "source": source}))
        return snapshot

    if not snapshot["market_open"]:
        return await finish(["Pasar sedang tutup."])

    frames = await _load_frames(session, symbol, analysis_timeframes(timeframe))
    m15 = frames[timeframe]
    expected = last_expected_candle_open(instrument.asset_class, now, timeframe)
    if m15.empty or (expected is not None and m15.index[-1] < expected):
        return await finish([f"Menunggu data candle {timeframe} terbaru dari provider."])
    if any(len(df) < strategy.min_bars for df in frames.values()):
        return await finish(["Histori candle belum cukup untuk menghitung indikator."])

    icfg = strategy.indicator_config
    ind = {tf: compute_indicators(df, icfg) for tf, df in frames.items()}
    m15, h1, h4 = ind[timeframe], ind[Timeframe.H1], ind[Timeframe.H4]
    snapshot["candle_time"] = m15.index[-1].isoformat()
    snapshot["last_close"] = float(m15["close"].iloc[-1])

    setting = (await settings_repo.get_all(session)).get(symbol)
    spread_pips = (
        setting.spread_pips
        if setting and setting.spread_pips is not None
        else instrument.typical_spread_pips
    )
    ctx = StrategyContext(
        instrument=instrument,
        now=now,
        m15=m15,
        h1=h1,
        h4=h4,
        spread_price=spread_pips * instrument.pip_size,
        active=to_view(active_row) if active_row else None,
        timeframe=timeframe,
    )
    blocked = await run_filters(m15, instrument, now, cfg.filters, calendar)
    await strategy.prepare(ctx)
    result = step(strategy, ctx, blocked, cfg.max_hold_candles, cfg.profit_close, cfg.trailing_stop)
    snapshot["filters"] = blocked
    snapshot["details"] = result.decision.details

    events: list[Signal] = []
    if result.exit and active_row:
        events.append(
            await _persist_exit(
                session, active_row, result.exit, narrator, instrument, strategy.narrate
            )
        )
        await session.flush()  # bebaskan slot ACTIVE sebelum sinyal baru dibuat

    entry = result.new_entry
    candle_time = m15.index[-1].to_pydatetime()
    if entry and not await signals_repo.exists(
        session, symbol, strategy.name, candle_time, entry.action.value
    ):
        signal = Signal(
            symbol=symbol,
            timeframe=timeframe.value,
            strategy=strategy.name,
            action=entry.action.value,
            candle_time=candle_time,
            entry=entry.entry,
            stop_loss=entry.stop_loss,
            take_profit=entry.take_profit,
            atr=entry.details.get("atr"),
            risk_reward=entry.details.get("risk_reward"),
            spread_pips=spread_pips,
            confidence=entry.confidence,
            confidence_label=confidence_label(entry.confidence),
            # entry_valid_minutes berlaku untuk M15; timeframe lain diskalakan sebanding
            entry_expires_at=candle_time
            + timeframe.delta
            + timedelta(minutes=cfg.entry_valid_minutes * timeframe.minutes / 15),
            reasons=entry.reasons,
            reason_text=await _describe(
                narrator,
                strategy.narrate,
                _signal_facts(instrument, entry, timeframe),
                entry.reasons,
            ),
            details=entry.details,
            status="ACTIVE",
        )
        session.add(signal)
        events.append(signal)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.warning(
            "%s: sinyal untuk candle %s sudah tersimpan (proses paralel)", symbol, candle_time
        )
        return await finish(result.decision.reasons)

    if events:
        latest = events[-1]
        snapshot.update(action=latest.action, is_new_event=True, event_ids=[e.id for e in events])
        snapshot["signal_id"] = latest.id if latest.action != Action.CLOSE.value else None
        for event in events:
            logger.info(
                "SINYAL %s %s (id=%s) entry=%s sl=%s tp=%s — %s",
                event.action,
                symbol,
                event.id,
                event.entry,
                event.stop_loss,
                event.take_profit,
                event.close_reason or event.confidence_label,
            )
            await redis.publish(
                EVENTS_CHANNEL,
                json.dumps(
                    {
                        "type": "signal",
                        "id": event.id,
                        "symbol": symbol,
                        "action": event.action,
                        "source": source,
                    }
                ),
            )
        reasons = list(events[-1].reasons)
    elif result.still_active:
        snapshot.update(action=result.still_active.action.value, signal_id=result.still_active.id)
        reasons = [
            f"Sinyal {result.still_active.action} masih aktif; belum ada alasan untuk menutup.",
            *result.decision.reasons[: 4 if source == "ai" else 1],
        ]
    else:
        snapshot.update(action=Action.WAIT.value, signal_id=None)
        reasons = result.decision.reasons
    return await finish(reasons)


async def get_latest_analysis(
    redis: Redis, symbol: str, source: str = "rule"
) -> dict[str, Any] | None:
    raw = await redis.get(analysis_key(symbol, source))
    return json.loads(raw) if raw else None


async def write_static_snapshot(
    redis: Redis, symbol: str, source: str, reason: str, *, idle: bool = False
) -> None:
    """Snapshot WAIT tetap (mis. sumber sinyal dinonaktifkan untuk instrumen ini)."""
    now = datetime.now(UTC)
    snapshot = {
        "symbol": symbol,
        "strategy": "disabled",
        "source": source,
        "analyzed_at": now.isoformat(),
        "next_candle_close": next_candle_close(now, Timeframe.M15).isoformat(),
        "market_open": True,
        "action": Action.WAIT.value,
        "is_new_event": False,
        "signal_id": None,
        "event_ids": [],
        "reasons": [reason],
        "filters": [],
        "details": {"idle": True} if idle else {},
        "candle_time": None,
        "last_close": None,
    }
    await redis.set(analysis_key(symbol, source), json.dumps(snapshot, default=str))
    await redis.publish(ANALYSIS_CHANNEL, json.dumps({"symbol": symbol, "source": source}))
