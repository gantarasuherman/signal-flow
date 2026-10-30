import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ai, backtest, chart, health, market, patterns, predictions, signals, ws
from app.api import settings as settings_api
from app.core.config import get_settings
from app.core.instruments import get_instruments
from app.core.logging import setup_logging
from app.core.redis import close_redis, get_redis
from app.data.providers import close_provider
from app.db.session import engine
from app.services.realtime import hub

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    instruments = get_instruments()  # gagal cepat bila config instrumen tidak valid
    logger.info(
        "API start — env=%s, provider=%s, instrumen=%s",
        settings.app_env,
        settings.data_provider,
        sorted(instruments),
    )
    listener = asyncio.create_task(hub.listen(get_redis(), ws.handle_event))
    yield
    listener.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await listener
    await close_provider()
    await close_redis()
    await engine.dispose()
    logger.info("API berhenti")


app = FastAPI(
    title="SignalFlow API",
    version="0.1.0",
    description="API sinyal trading M15. Sinyal bukan saran keuangan.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(market.router)
app.include_router(signals.router)
app.include_router(settings_api.router)
app.include_router(backtest.router)
app.include_router(ai.router)
app.include_router(patterns.router)
app.include_router(predictions.router)
app.include_router(chart.router)
app.include_router(ws.router)
