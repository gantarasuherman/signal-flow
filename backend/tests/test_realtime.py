import asyncio
import contextlib
import json
from typing import Any

from fakeredis import FakeAsyncRedis

from app.services.realtime import RealtimeHub
from app.services.signal_engine import EVENTS_CHANNEL


class FakeClient:
    def __init__(self, broken: bool = False) -> None:
        self.messages: list[dict[str, Any]] = []
        self.broken = broken

    async def send_text(self, data: str) -> None:
        if self.broken:
            raise RuntimeError("koneksi putus")
        self.messages.append(json.loads(data))


async def test_broadcast_drops_broken_clients() -> None:
    hub = RealtimeHub()
    ok, broken = FakeClient(), FakeClient(broken=True)
    hub.add(ok)
    hub.add(broken)
    await hub.broadcast({"type": "ping"})
    assert ok.messages == [{"type": "ping"}]
    assert hub.client_count == 1


async def test_listen_forwards_redis_events() -> None:
    hub = RealtimeHub()
    client = FakeClient()
    hub.add(client)
    redis = FakeAsyncRedis(decode_responses=True)
    received = asyncio.Event()

    async def handler(channel: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        received.set()
        return [{"type": "signal", "channel": channel, "id": data["id"]}]

    task = asyncio.create_task(hub.listen(redis, handler))
    try:
        for _ in range(50):  # tunggu sampai subscribe aktif
            if await redis.publish(EVENTS_CHANNEL, json.dumps({"id": 5, "symbol": "XAUUSD"})):
                break
            await asyncio.sleep(0.02)
        await asyncio.wait_for(received.wait(), timeout=2)
        await asyncio.sleep(0.05)
        assert client.messages == [{"type": "signal", "channel": EVENTS_CHANNEL, "id": 5}]
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
