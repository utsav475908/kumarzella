from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.modules.accounts.models import Account
from app.modules.instruments.models import Instrument
from app.modules.journal.models import Tag, TradeTag
from app.modules.playbooks.models import Playbook, PlaybookVersion
from app.modules.trades.models import Trade
from app.modules.trades.schemas import TagRef, TradeOut


def get_owned_trade(db: Session, user_id: UUID, trade_id: UUID) -> Trade:
    t = db.get(Trade, trade_id)
    if t is None or t.user_id != user_id:
        raise NotFound("Trade not found")
    return t


def check_playbook(db: Session, user_id: UUID, playbook_id: UUID | None) -> None:
    if playbook_id is None:
        return
    pb = db.get(Playbook, playbook_id)
    if pb is None or pb.user_id != user_id:
        raise ValidationFailed("Unknown playbook", code="invalid_playbook")


def check_tags(db: Session, user_id: UUID, tag_ids: list[UUID]) -> None:
    if not tag_ids:
        return
    found = set(db.scalars(select(Tag.id).where(Tag.user_id == user_id, Tag.id.in_(tag_ids))))
    if found != set(tag_ids):
        raise ValidationFailed("Unknown tag", code="invalid_tag")


def to_out(db: Session, rows: list[tuple[Trade, Instrument]]) -> list[TradeOut]:
    if not rows:
        return []
    ids = [t.id for t, _ in rows]
    accts = {a.id: a for a in db.scalars(select(Account).where(Account.id.in_({t.account_id for t, _ in rows})))}
    pb_ids = {t.playbook_id for t, _ in rows if t.playbook_id}
    pbs = {p.id: p.name for p in db.scalars(select(Playbook).where(Playbook.id.in_(pb_ids)))} if pb_ids else {}
    v_ids = {t.playbook_version_id for t, _ in rows if t.playbook_version_id}
    versions = dict(db.execute(select(PlaybookVersion.id, PlaybookVersion.version)
                               .where(PlaybookVersion.id.in_(v_ids))).tuples().all()) if v_ids else {}  # fmt: skip
    tags: dict[UUID, list[TagRef]] = defaultdict(list)
    for tt, tag in db.execute(
        select(TradeTag, Tag).join(Tag, Tag.id == TradeTag.tag_id).where(TradeTag.trade_id.in_(ids)).order_by(Tag.name)
    ):
        tags[tt.trade_id].append(TagRef.model_validate(tag))
    out = []
    for t, inst in rows:
        acct = accts[t.account_id]
        out.append(
            TradeOut.model_validate(
                {
                    **{c.key: getattr(t, c.key) for c in Trade.__table__.columns},
                    "account_name": acct.name,
                    "is_demo": acct.is_demo,
                    "symbol": inst.symbol,
                    "asset_class": inst.asset_class,
                    "multiplier": inst.multiplier,
                    "playbook_name": pbs.get(t.playbook_id) if t.playbook_id else None,
                    "playbook_version": versions.get(t.playbook_version_id),
                    "tags": tags.get(t.id, []),
                }
            )
        )
    return out


def neighbors(db: Session, t: Trade) -> tuple[UUID | None, UUID | None]:
    """Previous/next trade by open time across the user's trades (ties broken by id)."""
    base = select(Trade.id).where(Trade.user_id == t.user_id)
    prev_id = db.scalar(
        base.where(or_(Trade.opened_at < t.opened_at, and_(Trade.opened_at == t.opened_at, Trade.id < t.id)))
        .order_by(Trade.opened_at.desc(), Trade.id.desc())
        .limit(1)
    )
    next_id = db.scalar(
        base.where(or_(Trade.opened_at > t.opened_at, and_(Trade.opened_at == t.opened_at, Trade.id > t.id)))
        .order_by(Trade.opened_at, Trade.id)
        .limit(1)
    )
    return prev_id, next_id


def manual_fingerprint() -> str:
    return hashlib.sha256(f"manual:{uuid.uuid4()}".encode()).hexdigest()


def count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
