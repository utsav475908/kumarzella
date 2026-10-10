from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import get_current_user, owned_account
from app.core.errors import NotFound, ValidationFailed
from app.core.schemas import Page
from app.modules.auth.models import User
from app.modules.imports import csv_parser, service
from app.modules.imports.models import ImportJob, RawImportRecord
from app.modules.imports.schemas import (
    ImportJobOut,
    PresetOut,
    PreviewIn,
    PreviewOut,
    RawRecordOut,
    UploadOut,
)

router = APIRouter(prefix="/imports", tags=["imports"])


def _job(db: Session, user: User, job_id: UUID) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None or job.user_id != user.id:
        raise NotFound("Import not found")
    return job


@router.get("/presets", response_model=list[PresetOut])
def presets():
    return [PresetOut(key=k, **v) for k, v in csv_parser.PRESETS.items()]


@router.post("", response_model=UploadOut, status_code=201)
async def upload(
    account_id: UUID = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    acct = owned_account(db, user, account_id)
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed("File too large", code="file_too_large")
    job, mapping, preset, sample = service.upload(db, acct, file.filename or "upload.csv", data)
    return UploadOut(
        **ImportJobOut.model_validate(job).model_dump(),
        suggested_mapping=mapping,
        detected_preset=preset,
        sample_rows=sample,
    )


@router.get("", response_model=Page[ImportJobOut])
def list_imports(
    account_id: UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(ImportJob).where(ImportJob.user_id == user.id)
    if account_id:
        q = q.where(ImportJob.account_id == account_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(ImportJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{job_id}", response_model=ImportJobOut)
def get_import(job_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _job(db, user, job_id)


@router.post("/{job_id}/preview", response_model=PreviewOut)
def preview(job_id: UUID, data: PreviewIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = service.preview(db, _job(db, user, job_id), data)
    rows = list(
        db.scalars(
            select(RawImportRecord)
            .where(RawImportRecord.import_job_id == job.id)
            .order_by(RawImportRecord.row_number)
            .limit(50)
        )
    )
    return PreviewOut(job=job, rows=rows)


@router.get("/{job_id}/records", response_model=Page[RawRecordOut])
def records(
    job_id: UUID,
    status: str | None = Query(None, pattern="^(valid|rejected|duplicate|imported)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _job(db, user, job_id)
    q = select(RawImportRecord).where(RawImportRecord.import_job_id == job.id)
    if status:
        q = q.where(RawImportRecord.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = list(db.scalars(q.order_by(RawImportRecord.row_number).offset((page - 1) * page_size).limit(page_size)))
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/{job_id}/commit", response_model=ImportJobOut)
def commit(job_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.request_commit(db, _job(db, user, job_id))
