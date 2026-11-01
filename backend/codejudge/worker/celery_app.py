from __future__ import annotations

from celery import Celery
from kombu import Queue

from codejudge.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "codejudge",
    broker=settings.BROKER_URL,
    backend=settings.REDIS_URL,
    include=["codejudge.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.WORKER_CONCURRENCY,
    task_default_queue="codejudge",
    task_queues=(
        Queue("codejudge", queue_arguments={"x-max-priority": 10}),
    ),
    beat_schedule={
        "sweep-codejudge-submissions": {
            "task": "codejudge.worker.tasks.sweep_submissions",
            "schedule": 60.0,
        },
    },
)
