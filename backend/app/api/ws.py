"""WebSocket /ws untuk dashboard.

Pesan dari server:
  {"type": "hello", "server_time", "next_candle_close", "refresh_seconds"}
  {"type": "card", "data": InstrumentCard}      setelah setiap analisis (tiap 15 menit)
  {"type": "signal", "data": SignalView}        saat muncul BUY/SELL/CLOSE baru
  {"type": "live", "symbol", "timeframe", "candle", "updated_at", "market_open", "warning"}
  {"type": "pong"} / {"type": "error", "message"}

Pesan dari klien:
  {"action": "subscribe_live", "symbol": "XAUUSD", "timeframe": "M15"}
  {"action": "unsubscribe_live"}
  {"action": "ping"}
"""

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.instruments import Instrument, get_instrument
from app.core.market_hours import is_market_open
from app.core.redis import get_redis
from app.core.timeframes import Timeframe, next_candle_close
from app.data.providers import get_provider
from app.data.schemas import CandleDTO
from app.data.stream import TICKS_CHANNEL
from app.db.models import Signal
from app.db.session import SessionLocal
from app.repositories import instrument_settings as settings_repo
from app.services.live_candle import decode_live, fetch_live, is_streaming
from app.services.realtime import hub
from app.services.risk_prefs import get_risk_prefs
from app.services.signal_engine import ANALYSIS_CHANNEL, EVENTS_CHANNEL
from app.services.views import build_card, candle_out, load_signal_view
from app.services.watch import mark_watched

logger = logging.getLogger(__name__)
router = APIRouter()


# Klien yang sedang membuka grafik: websocket → (instrumen, timeframe, waktu kirim terakhir)
live_subscribers: dict[WebSocket, tuple[Instrument, Timeframe]] = {}
_last_tick_sent: dict[WebSocket, float] = {}
_offset_cache: dict[str, tuple[float, float]] = {}
TICK_MIN_INTERVAL = 0.5  # detik; batasi kiriman per klien
OFFSET_CACHE_SECONDS = 30


async def _price_offset(symbol: str) -> float:
    cached = _offset_cache.get(symbol)
    now = time.monotonic()
    if cached and now - cached[1] < OFFSET_CACHE_SECONDS:
        return cached[0]
    async with SessionLocal() as session:
        setting = (await settings_repo.get_all(session)).get(symbol)
    offset = setting.price_offset if setting else 0.0
    _offset_cache[symbol] = (offset, now)
    return offset


def live_message(
    instrument: Instrument,
    timeframe: Timeframe,
    candle: CandleDTO | None,
    updated_at: datetime | None,
    warning: str | None,
    offset: float,
    streaming: bool,
) -> dict[str, Any]:
    return {
        "type": "live",
        "symbol": instrument.symbol,
        "timeframe": timeframe.value,
        "candle": candle_out(candle, offset, instrument.digits).model_dump() if candle else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "market_open": is_market_open(instrument.asset_class, datetime.now(UTC)),
        "warning": warning,
        "streaming": streaming,
    }


async def push_tick(symbol: str) -> None:
    """Harga real-time dari streamer → kirim candle berjalan ke klien yang membuka grafiknya."""
    targets = [
        (ws, inst, tf) for ws, (inst, tf) in live_subscribers.items() if inst.symbol == symbol
    ]
    if not targets:
        return
    redis = get_redis()
    offset = await _price_offset(symbol)
    candles: dict[Timeframe, tuple[CandleDTO, datetime] | None] = {}
    now = time.monotonic()
    for ws, inst, tf in targets:
        if now - _last_tick_sent.get(ws, 0) < TICK_MIN_INTERVAL:
            continue
        if tf not in candles:
            raw = await redis.get(f"live:{symbol}:{tf.value}")
            candles[tf] = decode_live(raw) if raw else None
        cached = candles[tf]
        if cached is None:
            continue
        _last_tick_sent[ws] = now
        with contextlib.suppress(Exception):
            await ws.send_json(live_message(inst, tf, cached[0], cached[1], None, offset, True))


async def handle_event(channel: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """Dipanggil hub untuk setiap event Redis; mengembalikan pesan untuk disiarkan."""
    instrument = get_instrument(data.get("symbol", ""))
    if instrument is None:
        return []
    if channel == TICKS_CHANNEL:
        await push_tick(instrument.symbol)
        return []
    now = datetime.now(UTC)
    redis = get_redis()
    async with SessionLocal() as session:
        setting = (await settings_repo.get_all(session)).get(instrument.symbol)
        prefs = await get_risk_prefs(session)
        if channel == EVENTS_CHANNEL:
            signal = await session.get(Signal, data["id"])
            if signal is None:
                return []
            view = await load_signal_view(session, redis, signal, instrument, setting, prefs, now)
            return [{"type": "signal", "data": view.model_dump(mode="json")}]
        if channel == ANALYSIS_CHANNEL:
            source = data.get("source", "rule")
            card = await build_card(session, redis, instrument, setting, prefs, now, source)
            return [{"type": "card", "data": card.model_dump(mode="json")}]
    return []


async def stream_live(ws: WebSocket, instrument: Instrument, timeframe: Timeframe) -> None:
    """Live candle via polling (±20 detik) — untuk simbol yang tidak di-stream real-time.
    Simbol yang di-stream dikirim per detik oleh `push_tick`; loop ini hanya cadangan."""
    provider = get_provider()
    redis = get_redis()
    interval = max(get_settings().live_refresh_seconds, 5)
    last_sent: datetime | None = None
    while True:
        await mark_watched(redis, instrument.symbol)  # grafik masih terbuka → tetap dipantau
        candle, updated_at, warning = await fetch_live(provider, redis, instrument, timeframe)
        if updated_at != last_sent or warning:
            offset = await _price_offset(instrument.symbol)
            streaming = await is_streaming(redis, instrument.symbol)
            await ws.send_json(
                live_message(instrument, timeframe, candle, updated_at, warning, offset, streaming)
            )
            last_sent = updated_at
        await asyncio.sleep(interval)


async def _cancel(task: asyncio.Task[None] | None) -> None:
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    hub.add(ws)
    live_task: asyncio.Task[None] | None = None
    now = datetime.now(UTC)
    try:
        await ws.send_json(
            {
                "type": "hello",
                "server_time": now.isoformat(),
                "next_candle_close": next_candle_close(now, Timeframe.M15).isoformat(),
                "refresh_seconds": get_settings().live_refresh_seconds,
            }
        )
        while True:
            message = await ws.receive_json()
            action = message.get("action") if isinstance(message, dict) else None
            if action == "subscribe_live":
                instrument = get_instrument(str(message.get("symbol", "")))
                try:
                    timeframe = Timeframe(message.get("timeframe", "M15"))
                except ValueError:
                    timeframe = None
                if instrument is None or timeframe is None:
                    await ws.send_json({"type": "error", "message": "Simbol/timeframe tidak valid"})
                    continue
                await _cancel(live_task)
                live_subscribers[ws] = (instrument, timeframe)
                await mark_watched(get_redis(), instrument.symbol)
                live_task = asyncio.create_task(stream_live(ws, instrument, timeframe))
            elif action == "unsubscribe_live":
                live_subscribers.pop(ws, None)
                await _cancel(live_task)
                live_task = None
            elif action == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        hub.remove(ws)
        live_subscribers.pop(ws, None)
        _last_tick_sent.pop(ws, None)
        await _cancel(live_task)
