import json

from fakeredis import FakeAsyncRedis

from app.services.watch import WATCH_CHANNEL, WATCH_TTL_SECONDS, mark_watched, watched_symbols


async def test_first_watch_notifies_worker_then_only_refreshes() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(WATCH_CHANNEL)

    assert await mark_watched(redis, "XAUUSD") is True  # baru dibuka → beri tahu worker
    assert await mark_watched(redis, "XAUUSD") is False  # masih terbuka → hanya perpanjang
    assert 0 < await redis.ttl("watch:XAUUSD") <= WATCH_TTL_SECONDS

    messages = []
    for _ in range(4):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if msg:
            messages.append(json.loads(msg["data"]))
    assert messages == [{"symbol": "XAUUSD"}]


async def test_watched_symbols() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    await mark_watched(redis, "EURUSD")
    assert await watched_symbols(redis, ["EURUSD", "XAUUSD"]) == {"EURUSD"}
    assert await watched_symbols(redis, []) == set()
