"""Global filters shared by the trade journal and every analytics endpoint, so KPIs, charts and the
trade table always describe the same set of trades."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import Query
from sqlalchemy import Select, exists, or_, select

from app.modules.instruments.models import Instrument
from app.modules.journal.models import TradeTag
from app.modules.trades.models import Trade


@dataclass
class TradeFilters:
    account_ids: list[UUID] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    symbols: list[str] = field(default_factory=list)
    asset_classes: list[str] = field(default_factory=list)
    playbook_ids: list[UUID] = field(default_factory=list)
    no_playbook: bool = False
    tag_ids: list[UUID] = field(default_factory=list)
    direction: str | None = None
    session: str | None = None
    status: str | None = None
    outcome: str | None = None
    origin: str | None = None
    q: str | None = None

    def as_dict(self) -> dict:
        d = {
            "account_id": [str(a) for a in self.account_ids],
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "symbol": self.symbols,
            "asset_class": self.asset_classes,
            "playbook_id": [str(p) for p in self.playbook_ids] + (["none"] if self.no_playbook else []),
            "tag_id": [str(t) for t in self.tag_ids],
            "direction": self.direction,
            "session": self.session,
            "status": self.status,
            "outcome": self.outcome,
            "origin": self.origin,
            "q": self.q,
        }
        return {k: v for k, v in d.items() if v not in (None, [], "")}


def trade_filters(
    account_id: list[UUID] = Query(default_factory=list),
    date_from: date | None = None,
    date_to: date | None = None,
    symbol: list[str] = Query(default_factory=list),
    asset_class: list[Literal["stock", "etf", "option", "future", "forex", "crypto"]] = Query(default_factory=list),
    playbook_id: list[str] = Query(default_factory=list, description="Playbook ids, or 'none' for unassigned"),
    tag_id: list[UUID] = Query(default_factory=list),
    direction: Literal["long", "short"] | None = None,
    session: Literal["regular", "extended"] | None = None,
    status: Literal["open", "closed"] | None = None,
    outcome: Literal["win", "loss", "breakeven"] | None = None,
    origin: Literal["imported", "manual", "mixed"] | None = None,
    q: str | None = Query(None, max_length=64),
) -> TradeFilters:
    pb_ids: list[UUID] = []
    no_pb = False
    for p in playbook_id:
        if p == "none":
            no_pb = True
        else:
            pb_ids.append(UUID(p))
    return TradeFilters(
        account_ids=account_id, date_from=date_from, date_to=date_to,
        symbols=[s.strip().upper() for s in symbol if s.strip()], asset_classes=list(asset_class),
        playbook_ids=pb_ids, no_playbook=no_pb, tag_ids=tag_id, direction=direction, session=session,
        status=status, outcome=outcome, origin=origin, q=q.strip() if q else None,
    )  # fmt: skip


def apply_filters(stmt: Select, user_id: UUID, f: TradeFilters) -> Select:
    """Always scopes to the user first. Requires `Instrument` to be joinable from Trade."""
    stmt = stmt.where(Trade.user_id == user_id)
    if f.account_ids:
        stmt = stmt.where(Trade.account_id.in_(f.account_ids))
    if f.date_from:
        stmt = stmt.where(Trade.session_date >= f.date_from)
    if f.date_to:
        stmt = stmt.where(Trade.session_date <= f.date_to)
    if f.symbols:
        stmt = stmt.where(Instrument.symbol.in_(f.symbols))
    if f.asset_classes:
        stmt = stmt.where(Instrument.asset_class.in_(f.asset_classes))
    if f.playbook_ids or f.no_playbook:
        conds = []
        if f.playbook_ids:
            conds.append(Trade.playbook_id.in_(f.playbook_ids))
        if f.no_playbook:
            conds.append(Trade.playbook_id.is_(None))
        stmt = stmt.where(or_(*conds))
    if f.tag_ids:
        stmt = stmt.where(
            exists(select(TradeTag.trade_id).where(TradeTag.trade_id == Trade.id, TradeTag.tag_id.in_(f.tag_ids)))
        )
    if f.direction:
        stmt = stmt.where(Trade.direction == f.direction)
    if f.session:
        stmt = stmt.where(Trade.entry_session == f.session)
    if f.status:
        stmt = stmt.where(Trade.status == f.status)
    if f.outcome == "win":
        stmt = stmt.where(Trade.status == "closed", Trade.net_pnl > 0)
    elif f.outcome == "loss":
        stmt = stmt.where(Trade.status == "closed", Trade.net_pnl < 0)
    elif f.outcome == "breakeven":
        stmt = stmt.where(Trade.status == "closed", Trade.net_pnl == 0)
    if f.origin:
        stmt = stmt.where(Trade.origin == f.origin)
    if f.q:
        stmt = stmt.where(Instrument.symbol.ilike(f"%{f.q.upper().replace('%', '').replace('_', '')}%"))
    return stmt


def base_query() -> Select:
    return select(Trade, Instrument).join(Instrument, Instrument.id == Trade.instrument_id)
