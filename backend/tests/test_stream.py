import json
from datetime import UTC, datetime, timedelta

from fakeredis import FakeAsyncRedis

from app.core.instruments import Instrument
from app.core.timeframes import Timeframe
from app.data.schemas import CandleDTO
from app.data.stream import STATUS_KEY, TICKS_CHANNEL, PriceStreamer, merge_tick, streaming_symbols
from app.services.live_candle import decode_live, get_live_candle, is_streaming
from tests.test_live_candle import CountingProvider

NOW = datetime(2026, 10, 28, 6, 7, 30, tzinfo=UTC)  # Rabu, pasar buka


def test_merge_tick_updates_running_candle_and_rolls_over() -> None:
    c = merge_tick(None, 100.0, NOW, Timeframe.M15)
    assert c == CandleDTO(datetime(2026, 10, 28, 6, 0, tzinfo=UTC), 100, 100, 100, 100)
    c = merge_tick(c, 101.5, NOW + timedelta(seconds=5), Timeframe.M15)
    c = merge_tick(c, 99.0, NOW + timedelta(seconds=6), Timeframe.M15)
    assert (c.open, c.high, c.low, c.close) == (100, 101.5, 99.0, 99.0)
    # Batas candle M15 baru (06:15): candle baru dimulai dari harga tick
    nxt = merge_tick(c, 99.5, datetime(2026, 10, 28, 6, 15, 1, tzinfo=UTC), Timeframe.M15)
    assert nxt.open_time.minute == 15 and nxt.open == nxt.close == 99.5


async def test_streamer_writes_all_timeframes_and_publishes(xauusd: Instrument) -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(TICKS_CHANNEL)
    streamer = PriceStreamer(redis, {"XAUUSD": xauusd})

    assert await streamer.on_price("XAU/USD", 4001.234, NOW)
    assert await is_streaming(redis, "XAUUSD")
    for tf in Timeframe:
        candle, fetched_at = decode_live(await redis.get(f"live:XAUUSD:{tf.value}"))
        assert candle.close == 4001.23 and fetched_at == NOW

    messages = []
    for _ in range(5):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if msg:
            messages.append(json.loads(msg["data"]))
    assert messages == [{"symbol": "XAUUSD", "price": 4001.23, "time": NOW.isoformat()}]


async def test_streamer_ignores_closed_market_and_unknown_symbol(xauusd: Instrument) -> None:
    streamer = PriceStreamer(FakeAsyncRedis(decode_responses=True), {"XAUUSD": xauusd})
    saturday = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    assert not await streamer.on_price("XAU/USD", 4000.0, saturday)
    assert not await streamer.on_price("BTC/USD", 1.0, NOW)


async def test_live_candle_uses_stream_without_rest_request(eurusd: Instrument) -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    await PriceStreamer(redis, {"EURUSD": eurusd}).on_price("EUR/USD", 1.16123, NOW)
    provider = CountingProvider(NOW)
    live, _, _ = await get_live_candle(
        provider, redis, eurusd, Timeframe.M15, NOW + timedelta(seconds=1),
        refresh_seconds=20, reserved_credits=0,
    )  # fmt: skip
    assert live is not None and live.close == 1.16123
    assert provider.calls == 0


async def test_streaming_symbols_from_bridge_status(xauusd: Instrument, eurusd: Instrument) -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    instruments = {"XAUUSD": xauusd, "EURUSD": eurusd}
    assert await streaming_symbols(redis, instruments) == []
    await redis.set(STATUS_KEY, json.dumps({"success": ["XAU/USD"], "fails": ["EUR/USD"]}))
    assert await streaming_symbols(redis, instruments) == ["XAUUSD"]
