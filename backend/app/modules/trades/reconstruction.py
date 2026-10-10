"""Applies the position engine to persisted executions and keeps trades, allocations and positions in sync.

Trade identity is (anchor_execution_id, anchor_leg), so re-running reconstruction is idempotent and journal
metadata (notes, tags, stops, playbook) survives re-imports. If new executions change how fills group into
trades, journal data on a trade that no longer exists is moved to the trade that now contains its anchor fill.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.accounts.models import Account
from app.modules.analytics import formulas
from app.modules.attachments.models import Attachment
from app.modules.audit import service as audit
from app.modules.executions.models import Execution
from app.modules.instruments.models import Instrument
from app.modules.instruments.rules import entry_session, session_date
from app.modules.journal.models import TradeNote, TradeTag
from app.modules.positions.engine import Fill, ReconstructedTrade, reconstruct
from app.modules.trades.models import Position, Trade, TradeExecution

JOURNAL_FIELDS = ("planned_stop_price", "planned_target_price", "planned_risk_amount", "playbook_id",
                  "followed_plan", "rating")  # fmt: skip


@dataclass
class RebuildStats:
    trades_created: int = 0
    trades_updated: int = 0
    trades_removed: int = 0


def recompute_risk(trade: Trade, instrument: Instrument) -> None:
    trade.initial_risk = formulas.initial_risk(
        direction=trade.direction,
        entry_avg_price=trade.entry_avg_price,
        planned_stop_price=trade.planned_stop_price,
        peak_qty=trade.peak_qty,
        multiplier=instrument.multiplier,
        planned_risk_amount=trade.planned_risk_amount,
    )
    trade.r_multiple = formulas.r_multiple(trade.net_pnl, trade.initial_risk, trade.status)


def _apply(trade: Trade, rt: ReconstructedTrade, inst: Instrument) -> None:
    trade.direction = rt.direction
    trade.status = rt.status
    trade.origin = rt.origin
    trade.currency = inst.currency
    trade.opened_at = rt.opened_at
    trade.closed_at = rt.closed_at
    trade.session_date = session_date(rt.closed_at or rt.opened_at, inst.asset_class)
    trade.entry_session = entry_session(rt.opened_at, inst.asset_class)
    trade.entry_qty = rt.entry_qty
    trade.exit_qty = rt.exit_qty
    trade.peak_qty = rt.peak_qty
    trade.open_qty = rt.open_qty
    trade.entry_avg_price = rt.entry_avg_price
    trade.exit_avg_price = rt.exit_avg_price
    trade.gross_pnl = rt.gross_pnl
    trade.fees = rt.fees
    trade.net_pnl = rt.net_pnl
    trade.holding_seconds = rt.holding_seconds
    trade.execution_count = len({a.execution_id for a in rt.allocations})
    recompute_risk(trade, inst)


def rebuild_instrument(db: Session, account: Account, instrument_id: UUID) -> RebuildStats:
    # Serialize concurrent rebuilds of the same account+instrument within this transaction.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"{account.id}:{instrument_id}"})
    inst = db.get(Instrument, instrument_id)
    assert inst is not None
    execs = list(
        db.scalars(
            select(Execution).where(Execution.account_id == account.id, Execution.instrument_id == instrument_id)
        )
    )
    fills = [
        Fill(str(e.id), e.side, e.quantity, e.price, e.commission + e.fees, e.executed_at, e.sequence, e.source)
        for e in execs
    ]
    result = reconstruct(fills, inst.multiplier, account.accounting_policy)

    existing = {
        (t.anchor_execution_id, t.anchor_leg): t
        for t in db.scalars(select(Trade).where(Trade.account_id == account.id, Trade.instrument_id == instrument_id))
    }
    stats = RebuildStats()
    kept: dict[UUID, Trade] = {}
    exec_to_trade: dict[UUID, Trade] = {}
    for rt in result.trades:
        key = (UUID(rt.anchor_execution_id), rt.anchor_leg)
        trade = existing.get(key)
        if trade is None:
            trade = Trade(
                user_id=account.user_id,
                account_id=account.id,
                instrument_id=instrument_id,
                anchor_execution_id=key[0],
                anchor_leg=key[1],
            )
            _apply(trade, rt, inst)
            db.add(trade)
            db.flush()
            stats.trades_created += 1
        else:
            _apply(trade, rt, inst)
            stats.trades_updated += 1
        kept[trade.id] = trade
        db.execute(delete(TradeExecution).where(TradeExecution.trade_id == trade.id))
        for a in rt.allocations:
            db.add(
                TradeExecution(
                    trade_id=trade.id,
                    execution_id=UUID(a.execution_id),
                    role=a.role,
                    quantity=a.quantity,
                    fees_allocated=a.fees,
                    realized_pnl=a.realized_pnl,
                    position_after=a.position_after,
                )
            )
            exec_to_trade.setdefault(UUID(a.execution_id), trade)
    db.flush()

    for key, old in existing.items():
        if old.id in kept:
            continue
        successor = exec_to_trade.get(key[0])
        if successor is not None:
            _rehome_journal(db, old, successor)
            recompute_risk(successor, inst)
        audit.record(
            db,
            user_id=account.user_id,
            action="trade.removed_by_reconstruction",
            entity_type="trade",
            entity_id=old.id,
            data={"successor_trade_id": str(successor.id) if successor else None},
        )
        db.delete(old)
        stats.trades_removed += 1
    db.flush()

    open_trade = next((t for t in kept.values() if t.status == "open"), None)
    pos = db.scalar(select(Position).where(Position.account_id == account.id, Position.instrument_id == instrument_id))
    if result.position == 0:
        if pos is not None:
            db.delete(pos)
    else:
        if pos is None:
            pos = Position(user_id=account.user_id, account_id=account.id, instrument_id=instrument_id)
            db.add(pos)
        pos.quantity = result.position
        pos.avg_cost = result.avg_cost
        pos.open_trade_id = open_trade.id if open_trade else None
        pos.updated_at = utcnow()
    db.flush()
    return stats


def _rehome_journal(db: Session, old: Trade, new: Trade) -> None:
    db.execute(update(TradeNote).where(TradeNote.trade_id == old.id).values(trade_id=new.id))
    db.execute(update(Attachment).where(Attachment.trade_id == old.id).values(trade_id=new.id))
    existing_tags = set(db.scalars(select(TradeTag.tag_id).where(TradeTag.trade_id == new.id)))
    for tt in db.scalars(select(TradeTag).where(TradeTag.trade_id == old.id)):
        if tt.tag_id not in existing_tags:
            db.add(TradeTag(trade_id=new.id, tag_id=tt.tag_id, user_id=tt.user_id))
    for f in JOURNAL_FIELDS:
        if getattr(new, f) is None and getattr(old, f) is not None:
            setattr(new, f, getattr(old, f))


def rebuild_account(db: Session, account: Account, instrument_ids: set[UUID] | None = None) -> RebuildStats:
    if instrument_ids is None:
        instrument_ids = set(
            db.scalars(select(Execution.instrument_id).where(Execution.account_id == account.id).distinct())
        )
        instrument_ids |= set(db.scalars(select(Trade.instrument_id).where(Trade.account_id == account.id).distinct()))
    total = RebuildStats()
    for iid in sorted(instrument_ids, key=str):
        s = rebuild_instrument(db, account, iid)
        total.trades_created += s.trades_created
        total.trades_updated += s.trades_updated
        total.trades_removed += s.trades_removed
    return total
