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


@celery.task(name="marketdata.fetch", autoretry_for=(OperationalError,), retry_backoff=True, max_retries=3)
def fetch_marketdata_task(provider: str, symbol: str, days: list[str]) -> None:
    from datetime import date

    from app.modules.marketdata.providers import get_provider
    from app.modules.marketdata.service import fetch_days

    p = get_provider()
    if p is None or p.info.name != provider:
        log.warning("marketdata_task_provider_mismatch", provider=provider)
        return
    with SessionLocal() as db:
        failed = fetch_days(db, p, symbol, [date.fromisoformat(d) for d in days])
    log.info("marketdata_task_done", provider=provider, symbol=symbol, days=len(days), failed=len(failed))
