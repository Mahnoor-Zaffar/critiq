from __future__ import annotations

from arq.connections import RedisSettings

from critiq.apps.worker.tasks import review_pull_request
from critiq.core.config import settings


class WorkerSettings:
    functions = [review_pull_request]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    cron_jobs: list = []
