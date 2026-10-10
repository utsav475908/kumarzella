from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db, utcnow
from app.core.deps import get_current_user, owned_account
from app.core.errors import Conflict, NotFound
from app.modules.accounts.models import Account, CashTransaction
from app.modules.accounts.schemas import (
    AccountIn,
    AccountOut,
    AccountPatch,
    CashTransactionIn,
    CashTransactionOut,
)
from app.modules.audit import service as audit
from app.modules.auth.models import User
from app.modules.trades.reconstruction import rebuild_account

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(
    include_archived: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    q = select(Account).where(Account.user_id == user.id)
    if not include_archived:
        q = q.where(Account.archived_at.is_(None))
    return list(db.scalars(q.order_by(Account.created_at)))


@router.post("", response_model=AccountOut, status_code=201)
def create_account(data: AccountIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    acct = Account(user_id=user.id, **data.model_dump(), is_demo=data.account_type == "demo")
    db.add(acct)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("An account with this name already exists")
    audit.record(db, user_id=user.id, action="account.created", entity_type="account", entity_id=acct.id)
    db.commit()
    return acct


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return owned_account(db, user, account_id)


@router.patch("/{account_id}", response_model=AccountOut)
def patch_account(
    account_id: UUID, data: AccountPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    acct = owned_account(db, user, account_id)
    changes = data.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    policy_changed = "accounting_policy" in changes and changes["accounting_policy"] != acct.accounting_policy
    for k, v in changes.items():
        setattr(acct, k, v)
    if archived is not None:
        acct.archived_at = utcnow() if archived else None
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("An account with this name already exists")
    if policy_changed:
        rebuild_account(db, acct)
    audit.record(
        db, user_id=user.id, action="account.updated", entity_type="account", entity_id=acct.id,
        data={"fields": sorted(changes) + (["archived"] if archived is not None else [])},
    )  # fmt: skip
    db.commit()
    return acct


@router.delete("/{account_id}", status_code=204)
def delete_account(
    account_id: UUID, confirm_name: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Permanently delete an account and all its executions, trades and journal data.
    Requires `confirm_name` to equal the account name. Use /exports first to keep a copy."""
    acct = owned_account(db, user, account_id)
    if confirm_name != acct.name:
        raise Conflict("confirm_name does not match the account name", code="confirmation_mismatch")
    audit.record(db, user_id=user.id, action="account.deleted", entity_type="account", entity_id=acct.id)
    db.delete(acct)
    db.commit()
    return Response(status_code=204)


@router.get("/{account_id}/cash-transactions", response_model=list[CashTransactionOut])
def list_cash(account_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_account(db, user, account_id)
    return list(
        db.scalars(
            select(CashTransaction)
            .where(CashTransaction.account_id == account_id, CashTransaction.user_id == user.id)
            .order_by(CashTransaction.occurred_at)
        )
    )


@router.post("/{account_id}/cash-transactions", response_model=CashTransactionOut, status_code=201)
def add_cash(
    account_id: UUID, data: CashTransactionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    acct = owned_account(db, user, account_id)
    tx = CashTransaction(user_id=user.id, account_id=acct.id, currency=acct.base_currency, **data.model_dump())
    db.add(tx)
    db.flush()
    audit.record(db, user_id=user.id, action="cash_transaction.created", entity_type="account", entity_id=acct.id)
    db.commit()
    return tx


@router.delete("/{account_id}/cash-transactions/{tx_id}", status_code=204)
def delete_cash(account_id: UUID, tx_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_account(db, user, account_id)
    tx = db.get(CashTransaction, tx_id)
    if tx is None or tx.user_id != user.id or tx.account_id != account_id:
        raise NotFound("Transaction not found")
    db.delete(tx)
    audit.record(db, user_id=user.id, action="cash_transaction.deleted", entity_type="account", entity_id=account_id)
    db.commit()
    return Response(status_code=204)
