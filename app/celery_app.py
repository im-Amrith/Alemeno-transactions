from celery import Celery

from app.config import settings

celery_app = Celery(
    "txn_pipeline",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.imports = ("worker.tasks",)

# Explicit import (in addition to conf.imports) ensures the task is registered
# immediately when this module loads, regardless of how the worker process
# was invoked.
import worker.tasks  # noqa: E402,F401
