"""Worker: menjalankan siklus analisis tepat setelah setiap candle M15 ditutup.

Jalankan: python -m app.worker.main
"""

import asyncio
import json
import logging
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.analysis.config import get_analysis_config, get_strategy_for
from app.analysis.narrator import get_narrator
from app.core.config import ai_signals_enabled, get_settings
from app.core.instruments import Instrument, get_instruments
from app.core.logging import setup_logging
from app.core.market_hours import is_market_open
from app.core.redis import WORKER_HEARTBEAT_KEY, close_redis, get_redis
from app.core.timeframes import Timeframe, last_closed_candle_open
from app.data.errors import ProviderError, RateLimitError
from app.data.providers import close_provider, get_provider
from app.data.stream import PriceStreamer
from app.db.session import SessionLocal, engine
from app.repositories import signals as signals_repo
from app.services.backtest_jobs import fail_stale_runs, process_next_backtest
from app.services.candle_sync import sync_candles
from app.services.signal_engine import analyze_instrument, write_static_snapshot
from app.services.watch import WATCH_CHANNEL, watch_all_enabled, watched_symbols
from app.strategies import create_strategy

logger = logging.getLogger("worker")

CYCLE_LOCK_TTL_SECONDS = 600
SYNC_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.H4)
# Provider kadang butuh beberapa detik untuk memfinalkan candle yang baru tutup
FRESHNESS_RETRIES = 2
FRESHNESS_RETRY_SECONDS = 20


async def sync_instrument(instrument: Instrument) -> bool:
    """Sinkronkan M15/H1/H4. True bila candle M15 terbaru sudah tersedia."""
    provider = get_provider()
    m15_ready = False
    async with SessionLocal() as session:
        for timeframe in SYNC_TIMEFRAMES:
            for attempt in range(FRESHNESS_RETRIES + 1):
                result = await sync_candles(
                    session, provider, instrument, timeframe, datetime.now(UTC)
                )
                if result.up_to_date:
                    break
                if attempt < FRESHNESS_RETRIES:
                    await asyncio.sleep(FRESHNESS_RETRY_SECONDS)
            if timeframe is Timeframe.M15:
                m15_ready = result.up_to_date
                if not m15_ready:
                    logger.warning(
                        "%s: candle M15 terbaru belum tersedia dari provider", instrument.symbol
                    )
    return m15_ready


async def run_analysis_cycle() -> None:
    """Satu siklus untuk candle M15 yang baru ditutup: sinkron data lalu analisis sinyal."""
    now = datetime.now(UTC)
    candle_open = last_closed_candle_open(now, Timeframe.M15)
    redis = get_redis()

    # Lock per candle agar siklus tidak dobel bila ada lebih dari satu worker
    lock_key = f"lock:cycle:M15:{candle_open.isoformat()}"
    if not await redis.set(lock_key, now.isoformat(), nx=True, ex=CYCLE_LOCK_TTL_SECONDS):
        logger.warning("Siklus untuk candle %s sudah diproses, dilewati", candle_open)
        return

    instruments = get_instruments()
    logger.info(
        "Siklus analisis candle M15 %s (WIB %s) untuk %s",
        candle_open.isoformat(),
        candle_open.astimezone(get_settings().tz).strftime("%Y-%m-%d %H:%M"),
        sorted(instruments),
    )
    targets = await analysis_targets()
    for instrument in instruments.values():
        if instrument.symbol in targets:
            await sync_and_analyze(
                instrument, sync=is_market_open(instrument.asset_class, candle_open)
            )
        else:
            await mark_idle(instrument.symbol)
    await redis.set(WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    start_ai_cycle(targets)


async def analysis_targets() -> set[str]:
    """Instrumen yang dianalisis: yang sedang dibuka di dashboard + yang masih punya posisi
    aktif (agar CLOSE/TP/SL tidak terlewat). Semua bila ANALYZE_WATCHED_ONLY=false atau
    pengguna menyalakan "Pantau keempatnya"."""
    symbols = sorted(get_instruments())
    if not get_settings().analyze_watched_only:
        return set(symbols)
    targets = await watched_symbols(get_redis(), symbols)
    async with SessionLocal() as session:
        if await watch_all_enabled(session):
            return set(symbols)
        for symbol in symbols:
            if await signals_repo.get_active_for_symbol(session, symbol, source=None):
                targets.add(symbol)
    return targets


async def mark_idle(symbol: str) -> None:
    reason = f"Tidak dipantau — buka tab {symbol} untuk menganalisis instrumen ini."
    await write_static_snapshot(get_redis(), symbol, "rule", reason, idle=True)


_now_locks: dict[str, asyncio.Lock] = {}


async def analyze_now(symbol: str) -> None:
    """Tab baru dibuka di dashboard → sinkron & analisis segera (strategi lalu AI)."""
    instrument = get_instruments().get(symbol)
    if instrument is None:
        return
    lock = _now_locks.setdefault(symbol, asyncio.Lock())
    if lock.locked():
        return
    async with lock:
        logger.info("%s dipilih di dashboard → analisis sekarang", symbol)
        now = datetime.now(UTC)
        await sync_and_analyze(instrument, sync=is_market_open(instrument.asset_class, now))


async def listen_watch() -> None:
    """Dengarkan tab instrumen yang baru dibuka (channel dari API)."""
    while True:
        pubsub = get_redis().pubsub()
        try:
            await pubsub.subscribe(WATCH_CHANNEL)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    symbol = json.loads(message["data"]).get("symbol", "")
                    asyncio.create_task(analyze_now(symbol))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Listener watch terputus, mencoba lagi")
            await asyncio.sleep(3)
        finally:
            await pubsub.aclose()


_ai_lock = asyncio.Lock()
_ai_task: asyncio.Task[None] | None = None


def start_ai_cycle(symbols: set[str] | None = None) -> None:
    """Analisis AI berjalan di background agar siklus strategi tidak tertahan."""
    global _ai_task
    if ai_signals_enabled() and not _ai_lock.locked():
        _ai_task = asyncio.create_task(run_ai_cycle(symbols))


async def run_ai_cycle(symbols: set[str] | None = None) -> None:
    """AI hanya dijalankan lewat tombol "Analisis AI" (API). Di sini worker cukup memantau
    posisi AI yang masih aktif secara PASIF (tanpa memanggil Groq): TP/SL & batas waktu."""
    async with _ai_lock:
        params = {**get_analysis_config().strategies.get("ai_groq", {}), "passive": True}
        async with SessionLocal() as session:
            for instrument in get_instruments().values():
                active = await signals_repo.get_active_for_symbol(
                    session, instrument.symbol, source="ai"
                )
                if active is None:
                    continue
                try:
                    snapshot = await analyze_instrument(
                        session,
                        get_redis(),
                        instrument,
                        datetime.now(UTC),
                        strategy=create_strategy("ai_groq", params),
                    )
                    logger.info("%s [AI pasif]: %s", instrument.symbol, snapshot["action"])
                except Exception:
                    logger.exception("%s: error saat memantau posisi AI", instrument.symbol)


async def sync_and_analyze(instrument: Instrument, *, sync: bool = True) -> None:
    """Error satu instrumen tidak menghentikan instrumen lain."""
    symbol = instrument.symbol
    if sync:
        try:
            await sync_instrument(instrument)
        except RateLimitError as exc:
            logger.error("%s: kuota data habis — %s", symbol, exc)
        except ProviderError as exc:
            logger.error("%s: gagal mengambil data — %s", symbol, exc)
        except Exception:
            logger.exception("%s: error tak terduga saat sinkronisasi", symbol)
    try:
        async with SessionLocal() as session:
            snapshot = await analyze_instrument(session, get_redis(), instrument, datetime.now(UTC))
        logger.info("%s: %s — %s", symbol, snapshot["action"], " ".join(snapshot["reasons"][:2]))
    except Exception:
        logger.exception("%s: error saat analisis", symbol)


async def bootstrap() -> None:
    """Saat worker start: isi data awal lalu analisis, agar dashboard langsung terisi."""
    targets = await analysis_targets()
    for instrument in get_instruments().values():
        if instrument.symbol in targets:
            await sync_and_analyze(instrument)
        else:
            await mark_idle(instrument.symbol)
    start_ai_cycle(targets)


async def heartbeat() -> None:
    await get_redis().set(WORKER_HEARTBEAT_KEY, datetime.now(UTC).isoformat())


def build_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(
        run_analysis_cycle,
        CronTrigger(
            minute="0,15,30,45", second=settings.scheduler_delay_seconds, timezone=settings.tz
        ),
        id="m15_analysis",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(heartbeat, "interval", seconds=30, id="heartbeat")
    # Backtest dari dashboard: satu per satu, tidak tumpang tindih
    scheduler.add_job(
        process_next_backtest,
        "interval",
        seconds=10,
        id="backtests",
        max_instances=1,
        coalesce=True,
    )
    return scheduler


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "Data provider: %s | alasan AI (Groq): %s",
        settings.data_provider,
        "aktif" if get_narrator().uses_llm else "nonaktif",
    )
    for symbol in sorted(get_instruments()):  # validasi config strategi sejak awal
        strategy = get_strategy_for(symbol)
        logger.info("%s → strategi %s %s", symbol, strategy.name, strategy.params.model_dump())

    scheduler = build_scheduler()
    scheduler.start()
    job = scheduler.get_job("m15_analysis")
    logger.info("Worker aktif. Siklus M15 berikutnya: %s", job.next_run_time if job else "-")
    await heartbeat()
    await fail_stale_runs()
    bootstrap_task = asyncio.create_task(bootstrap())
    watch_task = asyncio.create_task(listen_watch())
    stream_task: asyncio.Task[None] | None = None
    api_key = settings.twelvedata_api_key.get_secret_value()
    if settings.data_provider == "twelvedata" and settings.twelvedata_streaming and api_key:
        streamer = PriceStreamer(get_redis(), get_instruments())
        stream_task = asyncio.create_task(streamer.run())

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    logger.info("Worker berhenti")
    bootstrap_task.cancel()
    watch_task.cancel()
    if stream_task:
        stream_task.cancel()
    scheduler.shutdown(wait=False)
    await close_provider()
    await close_redis()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
