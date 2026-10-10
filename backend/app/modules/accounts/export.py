"""Data export (portability) for the signed-in user. Excludes credentials and session data."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.modules.accounts.models import Account, CashTransaction
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.executions.models import Execution
from app.modules.journal.models import DayNote, Tag, TradeNote, TradeTag
from app.modules.playbooks.models import Playbook
from app.modules.trades.models import Trade, TradeExecution

router = APIRouter(prefix="/exports", tags=["exports"])


def _rows(db: Session, model, *where) -> list[dict]:
    cols = [c.key for c in model.__table__.columns]
    return [{c: getattr(r, c) for c in cols} for r in db.scalars(select(model).where(*where))]


@router.get("/me", summary="Download all of your trading data as JSON")
def export_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    trade_ids = select(Trade.id).where(Trade.user_id == user.id)
    payload = {
        "exported_at": datetime.now(UTC),
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name, "timezone": user.timezone},
        "accounts": _rows(db, Account, Account.user_id == user.id),
        "cash_transactions": _rows(db, CashTransaction, CashTransaction.user_id == user.id),
        "executions": _rows(db, Execution, Execution.user_id == user.id),
        "trades": _rows(db, Trade, Trade.user_id == user.id),
        "trade_executions": _rows(db, TradeExecution, TradeExecution.trade_id.in_(trade_ids)),
        "tags": _rows(db, Tag, Tag.user_id == user.id),
        "trade_tags": _rows(db, TradeTag, TradeTag.user_id == user.id),
        "trade_notes": _rows(db, TradeNote, TradeNote.user_id == user.id),
        "day_notes": _rows(db, DayNote, DayNote.user_id == user.id),
        "playbooks": _rows(db, Playbook, Playbook.user_id == user.id),
    }
    audit.record(db, user_id=user.id, action="user.exported", entity_type="user", entity_id=user.id)
    db.commit()
    return JSONResponse(
        jsonable_encoder(payload, custom_encoder={Decimal: str}),
        headers={"content-disposition": 'attachment; filename="edgeledger-export.json"'},
    )
