"""Playbook versions and per-trade rule assessments."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.modules.analytics import adherence as ad
from app.modules.instruments.models import Instrument
from app.modules.instruments.rules import market_local_time
from app.modules.playbooks.models import Playbook, PlaybookVersion, TradeChecklistAnswer
from app.modules.trades.models import Trade

RULE_FIELDS = (
    "instruments", "timeframe", "permitted_sessions", "entry_hour_start", "entry_hour_end", "entry_rules",
    "exit_rules", "stop_rules", "target_rules", "sizing_rules", "invalidation", "valid_examples",
    "invalid_examples", "require_stop", "max_risk_per_trade", "min_reward_risk", "max_trades_per_day",
    "pre_trade_checklist", "post_trade_checklist",
)  # fmt: skip


def owned_playbook(db: Session, user_id: UUID, playbook_id: UUID) -> Playbook:
    pb = db.get(Playbook, playbook_id)
    if pb is None or pb.user_id != user_id:
        raise NotFound("Playbook not found")
    return pb


def current_version(db: Session, pb: Playbook) -> PlaybookVersion:
    v = db.scalar(
        select(PlaybookVersion).where(
            PlaybookVersion.playbook_id == pb.id, PlaybookVersion.version == pb.current_version
        )
    )
    assert v is not None, f"playbook {pb.id} has no version {pb.current_version}"
    return v


def add_version(db: Session, pb: Playbook, rules: dict, change_note: str | None) -> PlaybookVersion:
    latest = db.scalar(select(PlaybookVersion.version).where(PlaybookVersion.playbook_id == pb.id)
                       .order_by(PlaybookVersion.version.desc()).limit(1))  # fmt: skip
    n = (latest or 0) + 1
    v = PlaybookVersion(playbook_id=pb.id, user_id=pb.user_id, version=n, change_note=change_note,
                        **{k: rules.get(k) for k in RULE_FIELDS if k in rules})  # fmt: skip
    for k, default in (("instruments", []), ("permitted_sessions", []), ("pre_trade_checklist", []),
                       ("post_trade_checklist", []), ("require_stop", False)):  # fmt: skip
        if getattr(v, k) is None:
            setattr(v, k, default)
    db.add(v)
    db.flush()
    pb.current_version = n
    return v


def to_rules(v: PlaybookVersion) -> ad.Rules:
    return ad.Rules(
        version_id=v.id, version=v.version, instruments=tuple(v.instruments or ()),
        permitted_sessions=tuple(v.permitted_sessions or ()), entry_hour_start=v.entry_hour_start,
        entry_hour_end=v.entry_hour_end, require_stop=v.require_stop, max_risk_per_trade=v.max_risk_per_trade,
        min_reward_risk=v.min_reward_risk, max_trades_per_day=v.max_trades_per_day,
        pre_trade_checklist=tuple((i["id"], i["text"]) for i in v.pre_trade_checklist or ()),
        post_trade_checklist=tuple((i["id"], i["text"]) for i in v.post_trade_checklist or ()),
    )  # fmt: skip


def assign_playbook(db: Session, t: Trade, playbook_id: UUID | None) -> None:
    """Assigning a playbook pins the trade to its current rules; removing it clears the pin."""
    if playbook_id is None:
        t.playbook_id = None
        t.playbook_version_id = None
        return
    if t.playbook_id == playbook_id and t.playbook_version_id is not None:
        return
    pb = db.get(Playbook, playbook_id)
    assert pb is not None
    t.playbook_id = playbook_id
    t.playbook_version_id = current_version(db, pb).id


def assess_trades(db: Session, rows: list[tuple[Trade, Instrument]]) -> dict[UUID, ad.Assessment]:
    """Assessments for trades that have a playbook version. Trades without one are left out."""
    rows = [(t, i) for t, i in rows if t.playbook_version_id is not None]
    if not rows:
        return {}
    versions = {v.id: v for v in db.scalars(
        select(PlaybookVersion).where(PlaybookVersion.id.in_({t.playbook_version_id for t, _ in rows})))}  # fmt: skip
    pinned = {t.id: t.playbook_version_id for t, _ in rows}
    answers: dict[UUID, dict[str, bool]] = defaultdict(dict)
    for a in db.scalars(select(TradeChecklistAnswer).where(TradeChecklistAnswer.trade_id.in_(list(pinned)))):
        if a.playbook_version_id == pinned[a.trade_id]:  # answers to an older version's checklist don't count
            answers[a.trade_id][a.item_id] = a.answer
    order = _trade_numbers(db, [t for t, _ in rows])
    out = {}
    for t, inst in rows:
        v = versions[t.playbook_version_id]
        facts = ad.Facts(
            symbol=inst.symbol, status=t.status, direction=t.direction, entry_session=t.entry_session,
            entry_hour=market_local_time(t.opened_at, inst.asset_class).hour, entry_avg_price=t.entry_avg_price,
            planned_stop_price=t.planned_stop_price, planned_target_price=t.planned_target_price,
            planned_risk_amount=t.planned_risk_amount, initial_risk=t.initial_risk, r_multiple=t.r_multiple,
            trade_number_of_day=order[t.id],
        )  # fmt: skip
        out[t.id] = ad.assess(facts, to_rules(v), answers.get(t.id, {}))
    return out


def _trade_numbers(db: Session, trades: list[Trade]) -> dict[UUID, int]:
    """1-based position of each trade among the same playbook's trades in its account on its session date."""
    keys = {(t.account_id, t.playbook_id, t.session_date) for t in trades}
    siblings = db.execute(
        select(Trade.id, Trade.account_id, Trade.playbook_id, Trade.session_date)
        .where(tuple_(Trade.account_id, Trade.playbook_id, Trade.session_date).in_(list(keys)))
        .order_by(Trade.opened_at, Trade.id)
    ).all()
    counter: dict[tuple, int] = defaultdict(int)
    out = {}
    for tid, acct, pb, day in siblings:
        counter[(acct, pb, day)] += 1
        out[tid] = counter[(acct, pb, day)]
    return out


def save_answers(db: Session, t: Trade, answers: list[tuple[str, bool | None]]) -> None:
    if t.playbook_version_id is None:
        raise ValidationFailed("Assign a playbook before answering its checklist", code="no_playbook")
    v = db.get(PlaybookVersion, t.playbook_version_id)
    assert v is not None
    phases = {i["id"]: "pre" for i in v.pre_trade_checklist} | {i["id"]: "post" for i in v.post_trade_checklist}
    for item_id, answer in answers:
        if item_id not in phases:
            raise ValidationFailed(f"Checklist item {item_id!r} is not in version {v.version} of this playbook",
                                   code="unknown_checklist_item")  # fmt: skip
        existing = db.get(TradeChecklistAnswer, (t.id, item_id))
        if answer is None:
            if existing is not None:
                db.delete(existing)
            continue
        if existing is None:
            db.add(TradeChecklistAnswer(trade_id=t.id, item_id=item_id, user_id=t.user_id,
                                        playbook_version_id=v.id, phase=phases[item_id], answer=answer))  # fmt: skip
        else:
            existing.answer, existing.playbook_version_id, existing.phase = answer, v.id, phases[item_id]
