"""Celery application and Beat schedule. Intervals come from settings (environment)."""
from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, worker_ready

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

settings = get_settings()

celery_app = Celery("dealhunter", broker=settings.redis_url, backend=settings.redis_url, include=["dh_workers.tasks"])


def build_schedule(s: Settings) -> dict:
    return {
        "collect-prices-and-score": {
            "task": "pipeline.run", "schedule": s.price_collection_minutes * 60.0,
        },
        "sync-catalogs": {"task": "catalog.sync_all", "schedule": s.catalog_sync_minutes * 60.0},
        "process-price-alerts": {"task": "alerts.process", "schedule": s.alert_check_minutes * 60.0},
        "send-notifications": {"task": "notifications.send", "schedule": s.notification_send_minutes * 60.0},
        "daily-ranking": {"task": "rankings.update", "schedule": crontab(hour=s.ranking_daily_hour_utc, minute=0)},
        "cleanup-old-cache": {"task": "cache.cleanup", "schedule": s.cache_cleanup_hours * 3600.0},
    }


celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,  # a job killed with its worker is re-queued, not silently lost
    worker_prefetch_multiplier=1,
    result_expires=3600,
    # A hung provider call or query must not occupy a worker forever. The soft limit lets the job log
    # its failure; the hard limit kills it. Both are well above the normal run time (seconds).
    task_soft_time_limit=900,
    task_time_limit=1200,
    worker_max_tasks_per_child=200,  # recycle processes to contain slow memory growth
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    beat_schedule=build_schedule(settings),
)


@setup_logging.connect
def _configure_logging(**_: object) -> None:
    configure_logging(settings.log_level)


@worker_ready.connect
def _bootstrap(**_: object) -> None:
    """On worker start, populate the catalogue and run one pipeline pass so the UI has data."""
    celery_app.send_task("catalog.bootstrap", countdown=10)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"
