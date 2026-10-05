"""Sends background jobs to the Celery workers by task name (the API never imports worker code)."""
from functools import lru_cache

from celery import Celery

from app.core.config import get_settings


@lru_cache
def _producer() -> Celery:
    url = get_settings().redis_url
    return Celery("dealhunter-api", broker=url, backend=url)


class CeleryQueue:
    def send(self, task: str, args: list) -> str:
        return _producer().send_task(task, args=args).id


def get_queue() -> CeleryQueue:
    return CeleryQueue()
