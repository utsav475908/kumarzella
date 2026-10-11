"""Advanced reports: playbook comparison, rule adherence, tags, holding time, months and costs by symbol.

Pure functions take closed-trade rows (see metrics.TradeRow) and, for adherence, the per-trade assessments from
playbooks.service.assess_trades. The database-facing entry points are ``report`` and ``adherence_report``.
Formulas are documented in docs/metrics.md ("Advanced reports" and "Rule adherence").
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import ZERO
from app.modules.analytics import metrics as mx
from app.modules.analytics.adherence import Assessment
from app.modules.analytics.metrics import TradeRow
from app.modules.journal.models import Tag, TradeTag
from app.modules.trades.filters import TradeFilters

OUTCOMES = ("followed", "broken", "incomplete", "no_rules")
ADHERENCE_NOTE = (
    "Adherence measures whether a trade met its playbook's rules, not whether it made money. Verified rules are "
    "checked from trade data; checklist items are the trader's own answers. Followed rate = followed / (followed + "
    "broken); incomplete trades (unknown rules or unanswered items) are left out of the rate."
)
HOLDING_BUCKETS: tuple[tuple[str, int | None], ...] = (
    ("< 1 min", 60), ("1-5 min", 300), ("5-15 min", 900), ("15-60 min", 3600), ("1-4 h", 4 * 3600),
    ("4-24 h", 86400), ("1-5 days", 5 * 86400), ("> 5 days", None),
)  # fmt: skip


def stats(trades: list[TradeRow]) -> dict:
    s = mx.summary(trades)
    return {k: s[k] for k in ("closed_trades", "net_pnl", "wins", "losses", "win_rate", "profit_factor",
                              "expectancy", "avg_r")}  # fmt: skip


def _net(trades: list[TradeRow]) -> Decimal | None:
    return mx.m(sum((t.net_pnl for t in trades), ZERO)) if trades else None


def _avg_r(trades: list[TradeRow]) -> Decimal | None:
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    return (sum(rs, ZERO) / len(rs)).quantize(mx.RATIO_Q) if rs else None


def followed_rate(counts: dict[str, int]) -> Decimal | None:
    return mx.ratio(Decimal(counts["followed"]), Decimal(counts["followed"] + counts["broken"]))


def adherence(trades: list[TradeRow], assessments: dict[UUID, Assessment]) -> dict:
    """Outcome groups, per-rule and per-checklist-item results over the trades that have an assessment."""
    assessed = [t for t in trades if t.id in assessments]
    by_outcome: dict[str, list[TradeRow]] = {o: [] for o in OUTCOMES}
    rules: dict[str, dict] = {}
    items: dict[str, dict] = {}
    broken = []
    for t in assessed:
        a = assessments[t.id]
        by_outcome[a.outcome].append(t)
        for r in a.rules:
            e = rules.setdefault(r.key, {"key": r.key, "label": r.label, "pass": [], "fail": [], "unknown": []})
            e[r.status].append(t)
        for c in a.checklist:
            e = items.setdefault(c["id"], {"id": c["id"], "text": c["text"], "phase": c["phase"],
                                           True: [], False: [], None: []})  # fmt: skip
            e["text"] = c["text"]  # the latest wording wins when an item was reworded in a later version
            e[c["answer"]].append(t)
        if a.outcome == "broken":
            broken.append({
                "trade_id": t.id, "symbol": t.symbol, "closed_at": t.closed_at, "net_pnl": mx.m(t.net_pnl),
                "r_multiple": t.r_multiple, "playbook_name": t.playbook_name, "version": a.version,
                "failed_rules": [r.label for r in a.rules if r.status == "fail"],
                "checklist_no": [c["text"] for c in a.checklist if c["answer"] is False],
            })  # fmt: skip
    counts = {o: len(v) for o, v in by_outcome.items()}
    return {
        "assessed_trades": len(assessed),
        "unassessed_trades": len(trades) - len(assessed),
        "counts": counts,
        "followed_rate": followed_rate(counts),
        "outcomes": [{"outcome": o, **stats(v)} for o, v in by_outcome.items()],
        "rules": sorted(
            [
                {
                    "key": e["key"],
                    "label": e["label"],
                    "passed": len(e["pass"]),
                    "failed": len(e["fail"]),
                    "unknown": len(e["unknown"]),
                    "fail_rate": mx.ratio(Decimal(len(e["fail"])), Decimal(len(e["pass"]) + len(e["fail"]))),
                    "net_pnl_when_passed": _net(e["pass"]),
                    "net_pnl_when_failed": _net(e["fail"]),
                    "avg_r_when_passed": _avg_r(e["pass"]),
                    "avg_r_when_failed": _avg_r(e["fail"]),
                }
                for e in rules.values()
            ],
            key=lambda r: (-r["failed"], r["label"]),
        ),  # fmt: skip
        "checklist": sorted(
            [
                {
                    "id": e["id"],
                    "text": e["text"],
                    "phase": e["phase"],
                    "yes": len(e[True]),
                    "no": len(e[False]),
                    "unanswered": len(e[None]),
                    "net_pnl_when_yes": _net(e[True]),
                    "net_pnl_when_no": _net(e[False]),
                }
                for e in items.values()
            ],
            key=lambda c: (c["phase"] != "pre", -c["no"], c["text"]),
        ),  # fmt: skip
        "broken_trades": sorted(broken, key=lambda b: b["closed_at"], reverse=True)[:100],
        "note": ADHERENCE_NOTE,
    }


def playbook_comparison(trades: list[TradeRow], assessments: dict[UUID, Assessment]) -> list[dict]:
    by: dict[UUID | None, list[TradeRow]] = defaultdict(list)
    for t in trades:
        by[t.playbook_id].append(t)
    out = []
    for k, ts in by.items():
        counts = {o: sum(1 for t in ts if t.id in assessments and assessments[t.id].outcome == o) for o in OUTCOMES}
        ex = mx.excursion_summary(ts)
        out.append({
            "key": None if k is None else str(k), "label": ts[0].playbook_name or "No playbook", **stats(ts),
            "avg_mae": ex["avg_mae"], "avg_mfe": ex["avg_mfe"], "trades_with_excursions": ex["trades_with_data"],
            "adherence": counts if k is not None else None,
            "followed_rate": followed_rate(counts) if k is not None else None,
        })  # fmt: skip
    return sorted(out, key=lambda g: (g["key"] is None, -(g["net_pnl"] or 0), g["label"]))


def bucketed(trades: list[TradeRow], key: Callable[[TradeRow], str], order: list[str]) -> list[dict]:
    by: dict[str, list[TradeRow]] = defaultdict(list)
    for t in trades:
        by[key(t)].append(t)
    return [{"key": k, "label": k, **stats(by[k])} for k in order if k in by]


def holding_bucket(seconds: int) -> str:
    return next(label for label, upper in HOLDING_BUCKETS if upper is None or seconds < upper)


def by_tag(trades: list[TradeRow], tags: dict[UUID, list[tuple[str, str]]]) -> list[dict]:
    """A trade with several tags counts once under each, so the rows do not sum to the total."""
    by: dict[tuple[str, str], list[TradeRow]] = defaultdict(list)
    for t in trades:
        for tag in tags.get(t.id, []):
            by[tag].append(t)
    rows = [{"tag": name, "category": cat, **stats(ts)} for (name, cat), ts in by.items()]
    return sorted(rows, key=lambda r: (r["net_pnl"], r["tag"]))


def costs_by_symbol(trades: list[TradeRow]) -> list[dict]:
    by: dict[str, list[TradeRow]] = defaultdict(list)
    for t in trades:
        by[t.symbol].append(t)
    rows = [{"symbol": s, "trades": len(ts), **mx.costs(ts), "net_pnl": _net(ts)} for s, ts in by.items()]
    return sorted(rows, key=lambda r: (-(r["total_fees"] or 0), r["symbol"]))


def _load(db: Session, user_id: UUID, f: TradeFilters, currency: str | None):
    from app.modules.analytics.service import load_with_rows
    from app.modules.playbooks.service import assess_trades

    trades, meta, rows = load_with_rows(db, user_id, f, currency)
    meta.pop("accounts")
    return trades, meta, assess_trades(db, rows)


def _warnings(trades: list[TradeRow], meta: dict) -> list[str]:
    w = []
    if meta["excluded_other_currency_trades"]:
        w.append(f"{meta['excluded_other_currency_trades']} closed trades in other currencies are excluded; "
                 f"choose a currency to see them. Amounts are never converted.")  # fmt: skip
    if 0 < len(trades) < mx.SMALL_SAMPLE:
        w.append(f"Small sample: {len(trades)} closed trades. Treat ratios as unreliable.")
    if meta["open_trades"]:
        w.append(f"{meta['open_trades']} open trades are excluded from these reports.")
    return w


def adherence_report(db: Session, user_id: UUID, f: TradeFilters, currency: str | None) -> dict:
    trades, meta, assessments = _load(db, user_id, f, currency)
    return {"filters": f.as_dict(), **meta, "warnings": _warnings(trades, meta), **adherence(trades, assessments)}


def report(db: Session, user_id: UUID, f: TradeFilters, currency: str | None) -> dict:
    trades, meta, assessments = _load(db, user_id, f, currency)
    tags: dict[UUID, list[tuple[str, str]]] = defaultdict(list)
    ids = [t.id for t in trades]
    if ids:
        for tid, name, cat in db.execute(
            select(TradeTag.trade_id, Tag.name, Tag.category).join(Tag, Tag.id == TradeTag.tag_id)
            .where(TradeTag.trade_id.in_(ids))
        ):  # fmt: skip
            tags[tid].append((name, cat))
    months = sorted({t.session_date.isoformat()[:7] for t in trades})
    return {
        "filters": f.as_dict(),
        **meta,
        "warnings": _warnings(trades, meta),
        "summary": stats(trades),
        "playbooks": playbook_comparison(trades, assessments),
        "adherence": adherence(trades, assessments),
        "by_tag": by_tag(trades, tags),
        "by_holding_time": bucketed(
            trades, lambda t: holding_bucket(t.holding_seconds), [b for b, _ in HOLDING_BUCKETS]
        ),  # fmt: skip
        "by_month": bucketed(trades, lambda t: t.session_date.isoformat()[:7], months),
        "costs_by_symbol": costs_by_symbol(trades),
    }
