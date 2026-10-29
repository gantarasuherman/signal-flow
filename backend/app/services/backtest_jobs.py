"""Antrian backtest: API membuat run 'queued', worker mengerjakannya satu per satu."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.backtest.runner import BacktestRequest, run_backtest
from app.db.models import BacktestRun
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


async def process_next_backtest() -> int | None:
    """Kerjakan satu run yang mengantre. Mengembalikan id run, atau None bila kosong."""
    async with SessionLocal() as session:
        run = (
            await session.execute(
                select(BacktestRun)
                .where(BacktestRun.status == "queued")
                .order_by(BacktestRun.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await session.commit()

        logger.info("Backtest #%s dimulai: %s", run.id, run.request)
        try:
            summary = await run_backtest(session, BacktestRequest.model_validate(run.request))
        except Exception as exc:
            logger.exception("Backtest #%s gagal", run.id)
            await session.rollback()
            run.status, run.error = "failed", str(exc)
        else:
            run.status, run.summary = "done", summary
        run.finished_at = datetime.now(UTC)
        await session.commit()
        logger.info("Backtest #%s selesai: %s", run.id, run.status)
        return run.id


async def fail_stale_runs() -> None:
    """Saat worker start: run 'running' yang tertinggal (worker mati) ditandai gagal."""
    async with SessionLocal() as session:
        await session.execute(
            update(BacktestRun)
            .where(BacktestRun.status == "running")
            .values(
                status="failed",
                error="Worker berhenti saat backtest berjalan",
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()
