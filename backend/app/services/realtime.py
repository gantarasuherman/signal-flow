"""Hub WebSocket: satu subscriber Redis pub/sub per proses API, disebarkan ke semua klien."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from redis.asyncio import Redis

from app.data.stream import TICKS_CHANNEL
from app.services.signal_engine import ANALYSIS_CHANNEL, EVENTS_CHANNEL

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], Awaitable[list[dict[str, Any]]]]


class Client(Protocol):
    async def send_text(self, data: str) -> None: ...


class RealtimeHub:
    def __init__(self) -> None:
        self._clients: set[Client] = set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def add(self, client: Client) -> None:
        self._clients.add(client)

    def remove(self, client: Client) -> None:
        self._clients.discard(client)

    async def broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, default=str)
        for client in list(self._clients):
            try:
                await client.send_text(payload)
            except Exception:
                # Koneksi putus: buang dari daftar, klien akan reconnect sendiri
                self._clients.discard(client)

    async def listen(self, redis: Redis, handler: Handler) -> None:
        """Ubah event Redis menjadi pesan WebSocket. Reconnect otomatis bila Redis putus."""
        while True:
            pubsub = redis.pubsub()
            try:
                await pubsub.subscribe(EVENTS_CHANNEL, ANALYSIS_CHANNEL, TICKS_CHANNEL)
                logger.info("Realtime hub mendengarkan %s, %s", EVENTS_CHANNEL, ANALYSIS_CHANNEL)
                async for message in pubsub.listen():
                    if message["type"] != "message" or not self._clients:
                        continue
                    try:
                        data = json.loads(message["data"])
                        for outgoing in await handler(message["channel"], data):
                            await self.broadcast(outgoing)
                    except Exception:
                        logger.exception("Gagal memproses event realtime %s", message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Koneksi pub/sub Redis terputus, mencoba lagi")
                await asyncio.sleep(3)
            finally:
                await pubsub.aclose()


hub = RealtimeHub()
