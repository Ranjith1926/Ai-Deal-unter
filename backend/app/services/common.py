"""Small shared helpers for the service layer."""
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AppSetting, ProviderSyncLog

logger = logging.getLogger("app.jobs")

SessionFactory = async_sessionmaker[AsyncSession]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobRun:
    """Counters a job fills in; persisted to ``provider_sync_logs`` when it ends."""

    processed: int = 0
    stored: int = 0
    events: int = 0
    invalid: int = 0
    missing: int = 0
    errors: int = 0
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.errors and self.processed:
            return "partial"
        if self.errors or self.error:
            return "failed"
        return "success"


@asynccontextmanager
async def job_log(
    factory: SessionFactory, provider: str, job_name: str, job_id: str | None = None
) -> AsyncIterator[JobRun]:
    """Record a job in ``provider_sync_logs`` and emit structured start/end log lines."""
    started = utcnow()
    async with factory() as session:
        row = ProviderSyncLog(provider=provider, job_name=job_name, status="running", started_at=started)
        session.add(row)
        await session.commit()
        row_id = row.id

    run = JobRun()
    logger.info("job started", extra={"job": job_name, "provider": provider, "job_id": job_id})
    try:
        yield run
    except Exception as exc:
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.errors += 1
        raise
    finally:
        finished = utcnow()
        async with factory() as session:
            row = await session.get(ProviderSyncLog, row_id)
            if row is not None:
                row.status = run.status
                row.records_processed = run.processed
                row.error_message = run.error
                row.completed_at = finished
                await session.commit()
        logger.info(
            "job finished",
            extra={
                "job": job_name, "provider": provider, "job_id": job_id, "status": run.status,
                "started_at": started.isoformat(), "ended_at": finished.isoformat(),
                "processed": run.processed, "stored": run.stored, "events": run.events,
                "invalid": run.invalid, "missing": run.missing, "errors": run.errors,
                "error": run.error,
            },
        )


async def load_scoring_config(factory: SessionFactory):
    """Defaults plus any admin overrides stored under ``app_settings['scoring_config']``."""
    from pydantic import ValidationError

    from app.engine.config import ScoringConfig

    async with factory() as session:
        setting = await session.get(AppSetting, "scoring_config")
    if setting is None:
        return ScoringConfig()
    try:
        return ScoringConfig().with_overrides(setting.value)
    except (ValidationError, ValueError):
        logger.exception("Invalid scoring_config in app_settings; using defaults")
        return ScoringConfig()
