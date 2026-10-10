"""Import workflow: upload -> preview (validate, detect duplicates) -> commit (transactional) -> reconstruct."""

from __future__ import annotations

import contextlib
import hashlib
from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import Conflict, ValidationFailed
from app.core.logging import log
from app.core.storage import get_storage
from app.modules.accounts.models import Account
from app.modules.audit import service as audit
from app.modules.executions.models import Execution
from app.modules.imports import csv_parser
from app.modules.imports.models import ImportJob, RawImportRecord
from app.modules.imports.schemas import ColumnMapping, ImportOptions, PreviewIn
from app.modules.instruments import service as instruments
from app.modules.instruments.rules import InstrumentSpec
from app.modules.trades.reconstruction import rebuild_account

ALLOWED_EXTENSIONS = (".csv", ".txt", ".tsv")


def upload(db: Session, account: Account, filename: str, data: bytes) -> tuple[ImportJob, dict, str | None, list]:
    s = get_settings()
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise ValidationFailed("Only .csv, .tsv or .txt files are accepted", code="unsupported_file_type")
    if len(data) > s.max_upload_bytes:
        raise ValidationFailed(
            f"File exceeds the {s.max_upload_bytes // (1024 * 1024)} MB limit", code="file_too_large"
        )
    try:
        headers, rows = csv_parser.read_csv(data, s.max_import_rows)
    except csv_parser.CsvError as e:
        raise ValidationFailed(str(e), code="invalid_csv")
    sha = hashlib.sha256(data).hexdigest()
    job = ImportJob(
        user_id=account.user_id, account_id=account.id, filename=filename[:255], file_sha256=sha,
        file_size=len(data), storage_key="", headers=headers, total_rows=len(rows),
    )  # fmt: skip
    db.add(job)
    db.flush()
    job.storage_key = f"imports/{account.user_id}/{job.id}.csv"
    get_storage().put(job.storage_key, data, "text/csv")
    previous = db.scalar(
        select(ImportJob.id).where(
            ImportJob.account_id == account.id,
            ImportJob.file_sha256 == sha,
            ImportJob.status == "completed",
            ImportJob.id != job.id,
        )
    )
    audit.record(
        db, user_id=account.user_id, action="import.uploaded", entity_type="import_job", entity_id=job.id,
        data={"rows": len(rows), "same_file_previously_imported": bool(previous)},
    )  # fmt: skip
    db.commit()
    mapping, preset = csv_parser.suggest_mapping(headers)
    return job, mapping, preset, rows[:10]


def _load_rows(job: ImportJob) -> list[dict[str, str]]:
    data = get_storage().get(job.storage_key)
    _, rows = csv_parser.read_csv(data, get_settings().max_import_rows)
    return rows


def _validate_mapping(job: ImportJob, m: ColumnMapping, opts: ImportOptions) -> None:
    missing = [c for c in m.model_dump().values() if c and c not in job.headers]
    if missing:
        raise ValidationFailed("Mapped columns are not in the file", details={"columns": missing})
    if not m.timestamp and not m.date:
        raise ValidationFailed("Map either a timestamp column or a date column")
    if not m.side and not opts.side_from_quantity_sign:
        raise ValidationFailed("Map a side column or enable side_from_quantity_sign")


def _existing_identity(db: Session, account_id: UUID, fingerprints: list[str], exec_ids: list[str]):
    by_fp: dict[str, UUID] = {}
    by_src: dict[str, UUID] = {}
    for chunk in range(0, len(fingerprints), 5000):
        part = fingerprints[chunk : chunk + 5000]
        for eid, fp in db.execute(
            select(Execution.id, Execution.fingerprint).where(
                Execution.account_id == account_id, Execution.fingerprint.in_(part)
            )
        ):
            by_fp[fp] = eid
    for chunk in range(0, len(exec_ids), 5000):
        part = exec_ids[chunk : chunk + 5000]
        for eid, src in db.execute(
            select(Execution.id, Execution.source_execution_id).where(
                Execution.account_id == account_id, Execution.source_execution_id.in_(part)
            )
        ):
            by_src[src] = eid
    return by_fp, by_src


def preview(db: Session, job: ImportJob, data: PreviewIn) -> ImportJob:
    if job.status not in ("uploaded", "previewed", "failed"):
        raise Conflict(f"Import is {job.status}; it can no longer be previewed")
    m, opts = data.mapping, data.options
    _validate_mapping(job, m, opts)
    rows = _load_rows(job)
    now = datetime.now(UTC)

    db.execute(delete(RawImportRecord).where(RawImportRecord.import_job_id == job.id))
    occurrences: Counter[str] = Counter()
    seen_src: set[str] = set()
    staged: list[tuple[int, dict, csv_parser.NormalizedRow | None, list[str], str | None]] = []
    for i, row in enumerate(rows, start=1):
        try:
            n = csv_parser.normalize_row(row, m, opts, now)
        except ValueError as e:
            staged.append((i, row, None, str(e).split("; "), None))
            continue
        base = n.base_fingerprint(str(job.account_id))
        fp = csv_parser.fingerprint(base, occurrences[base], n.source_execution_id)
        occurrences[base] += 1
        staged.append((i, row, n, [], fp))

    fps = [s[4] for s in staged if s[4]]
    srcs = [s[2].source_execution_id for s in staged if s[2] and s[2].source_execution_id]
    by_fp, by_src = _existing_identity(db, job.account_id, fps, srcs)

    counts = Counter()
    for i, row, n, errors, fp in staged:
        dup_of = None
        warnings = list(n.warnings) if n else []
        if n is None:
            status = "rejected"
        elif n.source_execution_id and n.source_execution_id in seen_src:
            status = "duplicate"
            warnings.append("duplicate execution id within this file")
        elif fp in by_fp or (n.source_execution_id and n.source_execution_id in by_src):
            status = "duplicate"
            dup_of = by_fp.get(fp) or by_src.get(n.source_execution_id or "")
            warnings.append("already imported")
        else:
            status = "valid"
        if n and n.source_execution_id:
            seen_src.add(n.source_execution_id)
        counts[status] += 1
        db.add(
            RawImportRecord(
                import_job_id=job.id, row_number=i, raw=row, normalized=n.to_json() if n else None, status=status,
                errors=errors, warnings=warnings, fingerprint=fp, duplicate_of_execution_id=dup_of,
            )
        )  # fmt: skip
    job.mapping = {"columns": m.model_dump(exclude_none=True), "options": opts.model_dump(), "preset": data.preset}
    job.total_rows = len(rows)
    job.valid_rows = counts["valid"]
    job.rejected_rows = counts["rejected"]
    job.duplicate_rows = counts["duplicate"]
    job.status = "previewed"
    job.error_message = None
    db.commit()
    return job


def request_commit(db: Session, job: ImportJob) -> ImportJob:
    if job.status != "previewed":
        raise Conflict(f"Import is {job.status}; preview it before committing", code="not_previewed")
    if job.valid_rows == 0:
        raise ValidationFailed("There are no valid, non-duplicate rows to import", code="nothing_to_import")
    s = get_settings()
    if not s.jobs_eager and job.valid_rows > s.large_import_row_threshold:
        job.status = "queued"
        db.commit()
        from app.worker import commit_import_task

        commit_import_task.delay(str(job.id))
        return job
    # A failure is recorded on the job (status=failed) and logged by process_commit; return the job to the caller.
    with contextlib.suppress(Exception):
        process_commit(db, job.id)
    db.refresh(job)
    return job


def process_commit(db: Session, job_id: UUID) -> None:
    """Commit an import in a single transaction. On failure nothing is written except the failure status."""
    job = db.scalar(select(ImportJob).where(ImportJob.id == job_id).with_for_update())
    if job is None or job.status not in ("previewed", "queued"):
        db.rollback()
        return
    job.status = "committing"
    job.attempts += 1
    db.commit()
    try:
        summary = _commit(db, job)
        job.status = "completed"
        job.summary = summary
        job.imported_rows = summary["executions_created"]
        job.committed_at = utcnow()
        audit.record(
            db, user_id=job.user_id, action="import.committed", entity_type="import_job", entity_id=job.id,
            data={k: summary[k] for k in ("executions_created", "trades_created", "trades_updated")},
        )  # fmt: skip
        db.commit()
        log.info("import_completed", import_job_id=str(job.id), executions=summary["executions_created"])
    except Exception as e:  # noqa: BLE001
        db.rollback()
        job = db.get(ImportJob, job_id)
        assert job is not None
        from sqlalchemy.exc import OperationalError

        retryable = isinstance(e, OperationalError) and job.attempts < 3
        job.status = "queued" if retryable else "failed"
        job.error_message = f"Import failed: {type(e).__name__}" + (" (will retry)" if retryable else "")
        audit.record(db, user_id=job.user_id, action="import.failed", entity_type="import_job", entity_id=job.id,
                     data={"error_type": type(e).__name__})  # fmt: skip
        db.commit()
        log.error("import_failed", import_job_id=str(job_id), error_type=type(e).__name__, attempts=job.attempts)
        raise


def _commit(db: Session, job: ImportJob) -> dict:
    account = db.get(Account, job.account_id)
    assert account is not None
    records = list(
        db.scalars(
            select(RawImportRecord)
            .where(RawImportRecord.import_job_id == job.id, RawImportRecord.status == "valid")
            .order_by(RawImportRecord.row_number)
        )
    )
    inst_cache: dict[tuple[str, str], UUID] = {}
    instrument_ids: set[UUID] = set()
    created = 0
    skipped = 0
    first: datetime | None = None
    last: datetime | None = None
    for rec in records:
        n = rec.normalized or {}
        key = (n["symbol"], n["asset_class"])
        if key not in inst_cache:
            from decimal import Decimal

            spec = InstrumentSpec(n["symbol"], n["asset_class"], n["currency"], Decimal(n["multiplier"]))
            inst_cache[key] = instruments.get_or_create(db, spec).id
        iid = inst_cache[key]
        executed_at = datetime.fromisoformat(n["executed_at"])
        stmt = (
            insert(Execution)
            .values(
                user_id=job.user_id,
                account_id=job.account_id,
                instrument_id=iid,
                source="import",
                import_job_id=job.id,
                raw_record_id=rec.id,
                source_execution_id=n["source_execution_id"],
                fingerprint=rec.fingerprint,
                side=n["side"],
                quantity=n["quantity"],
                price=n["price"],
                commission=n["commission"],
                fees=n["fees"],
                currency=n["currency"],
                executed_at=executed_at,
                sequence=rec.row_number,
                source_metadata={"row_number": rec.row_number, "filename": job.filename},
                created_at=utcnow(),
                updated_at=utcnow(),
            )  # fmt: skip
            .on_conflict_do_nothing()
            .returning(Execution.id)
        )
        eid = db.scalar(stmt)
        if eid is None:
            # Imported concurrently between preview and commit.
            rec.status = "duplicate"
            rec.warnings = [*rec.warnings, "already imported (detected at commit)"]
            skipped += 1
            continue
        rec.status = "imported"
        created += 1
        instrument_ids.add(iid)
        first = executed_at if first is None or executed_at < first else first
        last = executed_at if last is None or executed_at > last else last
    db.flush()
    stats = rebuild_account(db, account, instrument_ids)
    job.duplicate_rows += skipped
    return {
        "executions_created": created,
        "duplicates_skipped_at_commit": skipped,
        "rejected_rows": job.rejected_rows,
        "instruments": len(instrument_ids),
        "trades_created": stats.trades_created,
        "trades_updated": stats.trades_updated,
        "trades_removed": stats.trades_removed,
        "first_execution_at": first.isoformat() if first else None,
        "last_execution_at": last.isoformat() if last else None,
    }
