"""Live candle: candle yang sedang berjalan, di-cache di Redis agar semua viewer berbagi
satu request ke provider per interval refresh."""

import json
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.instruments import Instrument
from app.core.market_hours import is_market_open
from app.core.timeframes import Timeframe, floor_to_timeframe
from app.data.errors import ProviderError
from app.data.providers.base import DataProvider
from app.data.schemas import CandleDTO

logger = logging.getLogger(__name__)

# Diset oleh streamer (app.data.stream) setiap ada tick; kedaluwarsa bila stream berhenti
STREAM_ACTIVE_KEY = "stream:active:{symbol}"
STREAM_ACTIVE_TTL = 15


async def is_streaming(redis: Redis, symbol: str) -> bool:
    return bool(await redis.exists(STREAM_ACTIVE_KEY.format(symbol=symbol)))


def encode_live(candle: CandleDTO, fetched_at: datetime) -> str:
    return json.dumps(
        {
            "open_time": candle.open_time.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "fetched_at": fetched_at.isoformat(),
        }
    )


def decode_live(raw: str) -> tuple[CandleDTO, datetime]:
    data = json.loads(raw)
    candle = CandleDTO(
        open_time=datetime.fromisoformat(data["open_time"]),
        open=data["open"],
        high=data["high"],
        low=data["low"],
        close=data["close"],
    )
    return candle, datetime.fromisoformat(data["fetched_at"])


async def latest_cached_price(redis: Redis, symbol: str) -> tuple[float, datetime] | None:
    """Harga live terbaru dari cache (timeframe mana pun) tanpa request ke provider."""
    raws = await redis.mget([f"live:{symbol}:{tf.value}" for tf in Timeframe])
    best: tuple[float, datetime] | None = None
    for raw in raws:
        if raw:
            candle, fetched_at = decode_live(raw)
            if best is None or fetched_at > best[1]:
                best = (candle.close, fetched_at)
    return best


async def fetch_live(
    provider: DataProvider, redis: Redis, instrument: Instrument, timeframe: Timeframe
) -> tuple[CandleDTO | None, datetime | None, str | None]:
    """`get_live_candle` dengan pengaturan dari .env."""
    settings = get_settings()
    return await get_live_candle(
        provider,
        redis,
        instrument,
        timeframe,
        datetime.now(UTC),
        refresh_seconds=settings.live_refresh_seconds,
        reserved_credits=settings.twelvedata_reserved_daily,
    )


async def get_live_candle(
    provider: DataProvider,
    redis: Redis,
    instrument: Instrument,
    timeframe: Timeframe,
    now: datetime,
    *,
    refresh_seconds: int,
    reserved_credits: int,
) -> tuple[CandleDTO | None, datetime | None, str | None]:
    """Mengembalikan (candle berjalan, waktu diambil, peringatan)."""
    if not is_market_open(instrument.asset_class, now):
        return None, None, None

    current_open = floor_to_timeframe(now, timeframe)
    key = f"live:{instrument.symbol}:{timeframe.value}"
    cached_raw = await redis.get(key)
    cached = decode_live(cached_raw) if cached_raw else None
    if cached and cached[0].open_time != current_open:
        cached = None  # candle sudah berganti

    # Sedang streaming real-time (WebSocket di worker): cache selalu terbaru, tanpa REST.
    # Bila belum ada candle untuk timeframe ini, satu request REST mengisi open/high/low.
    if cached and await is_streaming(redis, instrument.symbol):
        return cached[0], cached[1], None

    is_fresh = cached and (now - cached[1]).total_seconds() < refresh_seconds
    # Hanya satu request per interval walau banyak viewer membuka grafik bersamaan
    if is_fresh or not await redis.set(f"{key}:lock", "1", nx=True, ex=refresh_seconds):
        return (cached[0], cached[1], None) if cached else (None, None, None)

    remaining = await provider.remaining_daily_credits()
    if remaining is not None and remaining <= reserved_credits:
        warning = "Kuota harian hampir habis; live candle dijeda agar sinyal M15 tetap jalan."
        return (cached[0], cached[1], warning) if cached else (None, None, warning)

    try:
        candles = await provider.fetch_candles(instrument, timeframe, limit=2)
    except ProviderError as exc:
        logger.warning("Live candle %s %s gagal: %s", instrument.symbol, timeframe, exc)
        warning = f"Live candle gagal diperbarui: {exc}"
        return (cached[0], cached[1], warning) if cached else (None, None, warning)

    running = next((c for c in candles if c.open_time == current_open), None)
    if running is None:
        return None, None, None
    fetched_at = datetime.now(UTC)
    await redis.set(key, encode_live(running, fetched_at), ex=timeframe.minutes * 60)
    return running, fetched_at, None
