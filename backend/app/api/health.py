import logging
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.core.instruments import get_instruments
from app.core.redis import WORKER_HEARTBEAT_KEY, get_redis
from app.core.timeframes import Timeframe, next_candle_close
from app.data.providers import SwitchableProvider, get_provider
from app.data.stream import streaming_symbols
from app.db.session import engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    data_provider: str
    database: bool
    redis: bool
    worker_last_heartbeat: str | None
    streaming: list[str]
    instruments: list[str]
    server_time: datetime
    next_m15_close: datetime


async def active_provider_name() -> str:
    provider = get_provider()
    if isinstance(provider, SwitchableProvider):
        return await provider.active_name()
    return get_settings().data_provider


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness probe ringan untuk healthcheck Docker."""
    return {"status": "ok"}


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Cek koneksi ke database, Redis, dan heartbeat worker."""
    db_ok = redis_ok = False
    heartbeat: str | None = None
    streaming: list[str] = []

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.exception("Health check database gagal")

    try:
        redis = get_redis()
        redis_ok = bool(await redis.ping())
        heartbeat = await redis.get(WORKER_HEARTBEAT_KEY)
        streaming = await streaming_symbols(redis, get_instruments())
    except Exception:
        logger.exception("Health check Redis gagal")

    now = datetime.now(UTC)
    return HealthResponse(
        status="ok" if db_ok and redis_ok else "degraded",
        data_provider=await active_provider_name(),
        database=db_ok,
        redis=redis_ok,
        worker_last_heartbeat=heartbeat,
        streaming=streaming,
        instruments=sorted(get_instruments()),
        server_time=now.astimezone(get_settings().tz),
        next_m15_close=next_candle_close(now, Timeframe.M15).astimezone(get_settings().tz),
    )
