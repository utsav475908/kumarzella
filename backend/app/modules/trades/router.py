from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, owned_account
from app.core.errors import NotFound, ValidationFailed
from app.core.schemas import Page
from app.modules.attachments.models import Attachment
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.executions.models import Execution
from app.modules.imports.models import ImportJob, RawImportRecord
from app.modules.instruments import service as instruments
from app.modules.instruments.models import Instrument
from app.modules.journal.models import DayNote, TradeNote, TradeTag
from app.modules.trades import service
from app.modules.trades.filters import TradeFilters, apply_filters, base_query, trade_filters
from app.modules.trades.models import Trade, TradeExecution
from app.modules.trades.reconstruction import rebuild_instrument, recompute_risk
from app.modules.trades.schemas import (
    AttachmentOut,
    AuditOut,
    ExecutionLeg,
    ManualTradeIn,
    NoteIn,
    NoteOut,
    SourceRef,
    TradeDetail,
    TradeOut,
    TradePatch,
)

router = APIRouter(prefix="/trades", tags=["trades"])

SORTS = {
    "opened_at": Trade.opened_at,
    "closed_at": Trade.closed_at,
    "net_pnl": Trade.net_pnl,
    "gross_pnl": Trade.gross_pnl,
    "r_multiple": Trade.r_multiple,
    "symbol": Instrument.symbol,
    "holding_seconds": Trade.holding_seconds,
}


@router.get("", response_model=Page[TradeOut])
def list_trades(
    f: TradeFilters = Depends(trade_filters),
    sort: Literal[
        "opened_at", "closed_at", "net_pnl", "gross_pnl", "r_multiple", "symbol", "holding_seconds"
    ] = "opened_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = apply_filters(base_query(), user.id, f)
    total = service.count(db, stmt)
    col = SORTS[sort]
    ordering = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = db.execute(stmt.order_by(ordering, Trade.id).offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=service.to_out(db, [(t, i) for t, i in rows]), total=total, page=page, page_size=page_size)


@router.get("/{trade_id}", response_model=TradeDetail)
def get_trade(trade_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = service.get_owned_trade(db, user.id, trade_id)
    inst = db.get(Instrument, t.instrument_id)
    assert inst is not None
    (out,) = service.to_out(db, [(t, inst)])
    legs = []
    rows = db.execute(
        select(TradeExecution, Execution)
        .join(Execution, Execution.id == TradeExecution.execution_id)
        .where(TradeExecution.trade_id == t.id)
        .order_by(Execution.executed_at, Execution.sequence, Execution.id)
    ).all()
    exec_ids = [e.id for _, e in rows]
    shared = set(
        db.scalars(
            select(TradeExecution.execution_id).where(
                TradeExecution.execution_id.in_(exec_ids), TradeExecution.trade_id != t.id
            )
        )
    )
    raw_ids = [e.raw_record_id for _, e in rows if e.raw_record_id]
    raws = (
        {r.id: r for r in db.scalars(select(RawImportRecord).where(RawImportRecord.id.in_(raw_ids)))} if raw_ids else {}
    )
    job_ids = {e.import_job_id for _, e in rows if e.import_job_id}
    jobs = {j.id: j for j in db.scalars(select(ImportJob).where(ImportJob.id.in_(job_ids)))} if job_ids else {}
    for a, e in rows:
        raw = raws.get(e.raw_record_id) if e.raw_record_id else None
        job = jobs.get(e.import_job_id) if e.import_job_id else None
        legs.append(
            ExecutionLeg(
                execution_id=e.id,
                executed_at=e.executed_at,
                side=e.side,
                quantity=e.quantity,
                price=e.price,
                commission=e.commission,
                fees=e.fees,
                source=e.source,
                source_execution_id=e.source_execution_id,
                role=a.role,
                allocated_quantity=a.quantity,
                fees_allocated=a.fees_allocated,
                realized_pnl=a.realized_pnl,
                position_after=a.position_after,
                shared_with_other_trade=e.id in shared,
                source_ref=SourceRef(
                    import_job_id=e.import_job_id,
                    filename=job.filename if job else None,
                    row_number=raw.row_number if raw else None,
                    raw=raw.raw if raw else None,
                )
                if e.source == "import"
                else None,
            )  # fmt: skip
        )
    notes = list(db.scalars(select(TradeNote).where(TradeNote.trade_id == t.id).order_by(TradeNote.created_at)))
    day_note = db.scalar(select(DayNote.body).where(DayNote.user_id == user.id, DayNote.day == t.session_date))
    atts = list(db.scalars(select(Attachment).where(Attachment.trade_id == t.id).order_by(Attachment.created_at)))
    prev_id, next_id = service.neighbors(db, t)
    sign = "+1 (long)" if t.direction == "long" else "-1 (short)"
    calc = {
        "gross_pnl": f"{sign} x (exit value - entry value) x multiplier {format(inst.multiplier.normalize(), 'f')}"
        if t.status == "closed"
        else "realized P&L of partial exits only (position still open)",
        "net_pnl": "gross_pnl - fees (commission + fees of every allocated execution)",
        "initial_risk": "planned_risk_amount if set, else |entry_avg_price - planned_stop_price| x peak_qty x multiplier",
        "r_multiple": "net_pnl / initial_risk (closed trades with known risk only)",
        "accounting_policy": owned_account(db, user, t.account_id).accounting_policy,
    }
    return TradeDetail(
        **out.model_dump(),
        executions=legs,
        notes=[NoteOut.model_validate(n) for n in notes],
        day_note=day_note,
        attachments=[AttachmentOut.model_validate(a) for a in atts],
        audit=[AuditOut.model_validate(a) for a in audit.list_for_entity(db, user.id, "trade", t.id)],
        prev_trade_id=prev_id,
        next_trade_id=next_id,
        calculation=calc,
    )


@router.patch("/{trade_id}", response_model=TradeOut)
def patch_trade(
    trade_id: UUID, data: TradePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    t = service.get_owned_trade(db, user.id, trade_id)
    changes = data.model_dump(exclude_unset=True)
    tag_ids = changes.pop("tag_ids", None)
    if "playbook_id" in changes:
        service.check_playbook(db, user.id, changes["playbook_id"])
    for k, v in changes.items():
        setattr(t, k, v)
    if tag_ids is not None:
        service.check_tags(db, user.id, tag_ids)
        db.execute(delete(TradeTag).where(TradeTag.trade_id == t.id))
        for tid in dict.fromkeys(tag_ids):
            db.add(TradeTag(trade_id=t.id, tag_id=tid, user_id=user.id))
    inst = db.get(Instrument, t.instrument_id)
    assert inst is not None
    recompute_risk(t, inst)
    audit.record(
        db, user_id=user.id, action="trade.updated", entity_type="trade", entity_id=t.id,
        data={"fields": sorted(changes) + (["tags"] if tag_ids is not None else [])},
    )  # fmt: skip
    db.commit()
    return service.to_out(db, [(t, inst)])[0]


@router.post("/manual", response_model=list[TradeOut], status_code=201)
def create_manual_trade(data: ManualTradeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Manual trade entry: the fills are stored as `source=manual` executions and reconstructed like imports."""
    acct = owned_account(db, user, data.account_id)
    service.check_playbook(db, user.id, data.playbook_id)
    try:
        inst = instruments.resolve(db, data.symbol, data.asset_class, data.currency, data.multiplier)
    except ValueError as e:
        raise ValidationFailed(str(e), code="invalid_instrument")
    execs = []
    for i, x in enumerate(sorted(data.executions, key=lambda x: x.executed_at)):
        e = Execution(
            user_id=user.id, account_id=acct.id, instrument_id=inst.id, source="manual",
            fingerprint=service.manual_fingerprint(), side=x.side, quantity=x.quantity, price=x.price,
            commission=x.commission, fees=x.fees, currency=inst.currency, executed_at=x.executed_at, sequence=i,
        )  # fmt: skip
        db.add(e)
        execs.append(e)
    db.flush()
    rebuild_instrument(db, acct, inst.id)
    ids = {e.id for e in execs}
    trades = list(
        db.scalars(
            select(Trade)
            .join(TradeExecution, TradeExecution.trade_id == Trade.id)
            .where(TradeExecution.execution_id.in_(ids))
            .distinct()
        )
    )
    for t in trades:
        if t.anchor_execution_id in ids:
            if data.planned_stop_price is not None:
                t.planned_stop_price = data.planned_stop_price
            if data.planned_target_price is not None:
                t.planned_target_price = data.planned_target_price
            if data.playbook_id:
                t.playbook_id = data.playbook_id
            recompute_risk(t, inst)
            if data.note:
                db.add(TradeNote(trade_id=t.id, user_id=user.id, body=data.note))
        audit.record(db, user_id=user.id, action="trade.manual_entry", entity_type="trade", entity_id=t.id)
    db.commit()
    return service.to_out(db, [(t, inst) for t in sorted(trades, key=lambda t: t.opened_at)])


@router.delete("/{trade_id}", status_code=204)
def delete_manual_trade(trade_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only trades made entirely of manual executions can be deleted. Imported data is immutable."""
    t = service.get_owned_trade(db, user.id, trade_id)
    execs = list(
        db.scalars(
            select(Execution)
            .join(TradeExecution, TradeExecution.execution_id == Execution.id)
            .where(TradeExecution.trade_id == t.id)
        )
    )
    if any(e.source != "manual" for e in execs):
        raise ValidationFailed("Only manually entered trades can be deleted", code="not_manual")
    acct = owned_account(db, user, t.account_id)
    iid = t.instrument_id
    audit.record(db, user_id=user.id, action="trade.deleted", entity_type="trade", entity_id=t.id)
    for e in execs:
        db.delete(e)
    db.flush()
    rebuild_instrument(db, acct, iid)
    db.commit()
    return Response(status_code=204)


@router.post("/{trade_id}/notes", response_model=NoteOut, status_code=201)
def add_note(trade_id: UUID, data: NoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = service.get_owned_trade(db, user.id, trade_id)
    n = TradeNote(trade_id=t.id, user_id=user.id, body=data.body)
    db.add(n)
    db.flush()
    audit.record(db, user_id=user.id, action="trade.note_added", entity_type="trade", entity_id=t.id)
    db.commit()
    return n


def _note(db: Session, user: User, trade_id: UUID, note_id: UUID) -> TradeNote:
    n = db.get(TradeNote, note_id)
    if n is None or n.user_id != user.id or n.trade_id != trade_id:
        raise NotFound("Note not found")
    return n


@router.patch("/{trade_id}/notes/{note_id}", response_model=NoteOut)
def edit_note(
    trade_id: UUID, note_id: UUID, data: NoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    n = _note(db, user, trade_id, note_id)
    n.body = data.body
    audit.record(db, user_id=user.id, action="trade.note_edited", entity_type="trade", entity_id=trade_id)
    db.commit()
    return n


@router.delete("/{trade_id}/notes/{note_id}", status_code=204)
def delete_note(trade_id: UUID, note_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(_note(db, user, trade_id, note_id))
    audit.record(db, user_id=user.id, action="trade.note_deleted", entity_type="trade", entity_id=trade_id)
    db.commit()
    return Response(status_code=204)
