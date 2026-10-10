"""Celery worker. Run with: celery -A app.worker worker --loglevel=INFO"""

from uuid import UUID

from celery import Celery
from sqlalchemy.exc import OperationalError

import app.models  # noqa: F401  (register every table)
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging, log

settings = get_settings()
celery = Celery("edgeledger", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_always_eager=settings.jobs_eager,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
)
configure_logging()


@celery.task(
    name="imports.commit",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    max_retries=3,
)
def commit_import_task(job_id: str) -> None:
    from app.modules.imports.service import process_commit

    log.info("import_task_started", import_job_id=job_id)
    with SessionLocal() as db:
        process_commit(db, UUID(job_id))
