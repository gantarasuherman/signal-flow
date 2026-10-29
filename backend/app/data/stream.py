"""Harga real-time per detik (berjalan di worker).

Koneksi WebSocket ke Twelve Data dipegang service `streamer` (Node, streamer/bridge.mjs)
karena klien WebSocket Python tidak bisa menyelesaikan handshake ke server mereka. Service
itu meneruskan harga mentah ke channel Redis `ticks:raw`; di sini setiap harga memperbarui
candle berjalan semua timeframe (`live:{symbol}:{tf}`, format sama dengan live candle REST)
lalu dipublikasikan ke channel `ticks` agar grafik dashboard bergerak tiap detik.
Simbol yang ditolak paket Twelve Data tetap memakai live candle REST (±20 detik).
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.core.instruments import Instrument
from app.core.market_hours import is_market_open
from app.core.timeframes import Timeframe, floor_to_timeframe
from app.data.schemas import CandleDTO
from app.services.live_candle import (
    STREAM_ACTIVE_KEY,
    STREAM_ACTIVE_TTL,
    decode_live,
    encode_live,
)

logger = logging.getLogger(__name__)

RAW_TICKS_CHANNEL = "ticks:raw"  # dari streamer Node: {"symbol": "XAU/USD", "price": 4040.5}
TICKS_CHANNEL = "ticks"  # ke API/dashboard: {"symbol": "XAUUSD", "price", "time"}
WANTED_KEY = "stream:wanted"  # simbol provider yang diminta untuk di-stream
STATUS_KEY = "stream:status"  # {"success": [...], "fails": [...]} dari streamer Node


def merge_tick(candle: CandleDTO | None, price: float, now: datetime, tf: Timeframe) -> CandleDTO:
    """Gabungkan satu harga ke candle berjalan; candle baru dimulai di batas timeframe."""
    open_time = floor_to_timeframe(now, tf)
    if candle is None or candle.open_time != open_time:
        return CandleDTO(open_time, price, price, price, price)
    return CandleDTO(open_time, candle.open, max(candle.high, price), min(candle.low, price), price)


async def streaming_symbols(redis: Redis, instruments: dict[str, Instrument]) -> list[str]:
    """Simbol internal yang sedang di-stream real-time (menurut streamer)."""
    raw = await redis.get(STATUS_KEY)
    if not raw:
        return []
    by_provider = {i.provider_symbol: i.symbol for i in instruments.values()}
    success = json.loads(raw).get("success", [])
    return sorted(by_provider[s] for s in success if s in by_provider)


class PriceStreamer:
    def __init__(self, redis: Redis, instruments: dict[str, Instrument]) -> None:
        self._redis = redis
        self._by_provider = {i.provider_symbol: i for i in instruments.values()}

    async def on_price(self, provider_symbol: str, price: float, now: datetime) -> bool:
        instrument = self._by_provider.get(provider_symbol)
        if instrument is None or not is_market_open(instrument.asset_class, now):
            return False
        symbol = instrument.symbol
        price = instrument.round_price(price)
        for tf in Timeframe:
            key = f"live:{symbol}:{tf.value}"
            raw = await self._redis.get(key)
            cached = decode_live(raw)[0] if raw else None
            candle = merge_tick(cached, price, now, tf)
            await self._redis.set(key, encode_live(candle, now), ex=tf.minutes * 60)
        await self._redis.set(STREAM_ACTIVE_KEY.format(symbol=symbol), "1", ex=STREAM_ACTIVE_TTL)
        await self._redis.publish(
            TICKS_CHANNEL, json.dumps({"symbol": symbol, "price": price, "time": now.isoformat()})
        )
        return True

    async def run(self) -> None:
        """Daftarkan simbol yang diminta lalu proses harga dari streamer Node selamanya."""
        await self._redis.set(WANTED_KEY, json.dumps(sorted(self._by_provider)))
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(RAW_TICKS_CHANNEL)
                logger.info("Menunggu harga real-time dari service streamer")
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        await self.on_price(data["symbol"], float(data["price"]), datetime.now(UTC))
                    except (KeyError, TypeError, ValueError):
                        logger.warning("Tick tidak valid dari streamer: %s", message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Koneksi pub/sub tick terputus, mencoba lagi")
                await asyncio.sleep(3)
            finally:
                await pubsub.aclose()
