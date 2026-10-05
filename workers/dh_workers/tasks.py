"""Celery tasks. Each is a thin wrapper over a reusable service in ``app.services``.

Task / spec mapping
  collect_amazon_prices, collect_flipkart_prices  -> prices.collect (normalise + save history + detect
                                                      price drops / historical lows / back in stock)
  normalize_products, match_products              -> run inside catalog.sync (app.services.catalog)
  calculate_deal_scores, calculate_value_scores   -> scores.calculate (one pass; value uses deal output)
  update_best_deals                               -> rankings.update
  process_price_alerts, send_notifications, cleanup_old_cache -> same names below
"""
import asyncio
import logging
from typing import Any, Awaitable, Callable

from celery import chain, group

from app.core.config import get_settings
from app.db.session import worker_session_factory
from app.providers.registry import ProviderRegistry, build_registry
from app.services import admin as admin_service
from app.services import alerts, catalog, notifications, prices, rankings, scoring
from app.services.common import JobRun, SessionFactory, job_log, load_scoring_config
from app.services.locks import job_lock
from dh_workers.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()
_registry: ProviderRegistry | None = None


def registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = build_registry(settings)
    return _registry


def _run_job(
    name: str, provider: str, job_id: str | None, body: Callable[[SessionFactory, Any, JobRun], Awaitable[None]],
    lock_name: str | None = None,
) -> dict:
    """Run an async job body with a lock, a job-log row and failure isolation."""
    with job_lock(settings.redis_url, lock_name or f"{name}:{provider}", settings.job_lock_ttl_seconds) as acquired:
        if not acquired:
            logger.info("job skipped: already running", extra={"job": name, "provider": provider})
            return {"job": name, "provider": provider, "status": "skipped"}

        async def go() -> dict:
            current: dict[str, JobRun] = {}
            try:
                async with worker_session_factory() as factory:
                    config = await load_scoring_config(factory)
                    async with job_log(factory, provider, name, job_id) as run:
                        current["run"] = run
                        await body(factory, config, run)
            except Exception as exc:
                # job_log has already recorded the failure. Do not raise: a failed provider
                # must not break downstream tasks or the other provider's job.
                logger.exception("job failed", extra={"job": name, "provider": provider, "job_id": job_id})
                error = current["run"].error if "run" in current else f"{type(exc).__name__}: {exc}"
                return {"job": name, "provider": provider, "status": "failed", "error": error}
            run = current["run"]
            return {"job": name, "provider": provider, "status": run.status, "processed": run.processed,
                    "stored": run.stored, "events": run.events}

        return asyncio.run(go())


# ---------------------------------------------------------------- catalogue
async def _disabled_by_admin(factory: SessionFactory, provider: str, run: JobRun) -> bool:
    """An administrator can switch a provider off in the dashboard; its jobs then do nothing."""
    async with factory() as session:
        if await admin_service.is_provider_enabled(session, provider):
            return False
    run.extra["skipped"] = "provider disabled by an administrator"
    logger.info("provider disabled by administrator; job skipped", extra={"provider": provider})
    return True


def _sync(provider: str, job_id: str | None) -> dict:
    if provider not in registry().names():
        return {"job": "sync_catalog", "provider": provider, "status": "disabled"}
    handle = registry().get(provider)

    async def body(factory: SessionFactory, config: Any, run: JobRun) -> None:
        if await _disabled_by_admin(factory, provider, run):
            return
        await catalog.sync_catalog(factory, handle, config, run)

    return _run_job("sync_catalog", provider, job_id, body)


@celery_app.task(name="catalog.sync", bind=True)
def sync_catalog(self, provider: str) -> dict:
    return _sync(provider, self.request.id)


@celery_app.task(name="catalog.sync_all", bind=True)
def sync_all_catalogs(self) -> list[dict]:
    # Plain calls (not subtasks): Celery forbids waiting on a subtask's result inside a task.
    return [_sync(name, self.request.id) for name in registry().names()]


@celery_app.task(name="catalog.bootstrap", bind=True)
def bootstrap(self) -> str:
    """First-run: discover products, then run a full pipeline pass."""
    for name in registry().names():
        _sync(name, self.request.id)
    run_pipeline.delay()
    return "bootstrapped"


# ---------------------------------------------------------------- prices
def _collect(task: Any, provider: str) -> dict:
    if provider not in registry().names():
        return {"job": "collect_prices", "provider": provider, "status": "disabled"}
    handle = registry().get(provider)

    async def body(factory: SessionFactory, config: Any, run: JobRun) -> None:
        if await _disabled_by_admin(factory, provider, run):
            return
        await prices.collect_prices(factory, handle, config, run, settings.price_batch_size)

    return _run_job("collect_prices", provider, task.request.id, body)


@celery_app.task(name="prices.collect_amazon", bind=True)
def collect_amazon_prices(self) -> dict:
    return _collect(self, "amazon")


@celery_app.task(name="prices.collect_flipkart", bind=True)
def collect_flipkart_prices(self) -> dict:
    return _collect(self, "flipkart")


# ---------------------------------------------------------------- scores & rankings
@celery_app.task(name="scores.calculate", bind=True)
def calculate_scores(self, *_: Any) -> dict:
    async def body(factory: SessionFactory, config: Any, run: JobRun) -> None:
        await scoring.calculate_scores(factory, config, run)

    return _run_job("calculate_scores", "all", self.request.id, body)


@celery_app.task(name="rankings.update", bind=True)
def update_best_deals(self, *_: Any) -> dict:
    async def body(factory: SessionFactory, config: Any, run: JobRun) -> None:
        await rankings.update_best_deals(factory, settings.redis_url, run)

    return _run_job("update_best_deals", "all", self.request.id, body)


@celery_app.task(name="pipeline.run")
def run_pipeline() -> str:
    """Collect from every provider in parallel, then score and re-rank.

    Collection tasks return a status instead of raising, so one failing provider does not
    stop the other or the scoring that follows (stale data is flagged by the scorer).
    """
    collectors = [collect_amazon_prices.si(), collect_flipkart_prices.si()]
    chain(group(collectors), calculate_scores.si(), update_best_deals.si()).apply_async()
    return "pipeline scheduled"


# ---------------------------------------------------------------- alerts & notifications
@celery_app.task(name="alerts.process", bind=True)
def process_price_alerts(self) -> dict:
    async def body(factory: SessionFactory, config: Any, run: JobRun) -> None:
        await alerts.process_price_alerts(factory, config, run)

    return _run_job("process_price_alerts", "all", self.request.id, body)


@celery_app.task(name="notifications.send", bind=True)
def send_notifications(self) -> dict:
    async def body(factory: SessionFactory, config: Any, run: JobRun) -> None:
        await notifications.dispatch_pending(factory, run)

    return _run_job("send_notifications", "all", self.request.id, body)


@celery_app.task(name="cache.cleanup", bind=True)
def cleanup_old_cache(self) -> dict:
    async def body(factory: SessionFactory, config: Any, run: JobRun) -> None:
        await rankings.cleanup_old_cache(settings.redis_url, run)

    return _run_job("cleanup_old_cache", "all", self.request.id, body)
