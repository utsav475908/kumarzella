"""Playbook rule adherence. See docs/metrics.md, "Rule adherence".

Two kinds of evidence are kept apart and never merged into one number:

* verified rules: checked by the system from trade data (instrument, session, entry hour, stop set, risk limit,
  planned reward:risk, trades per day, loss within planned risk). Each is pass, fail or unknown (missing data).
* checklist answers: the trader's own yes/no confirmation of items that need chart inspection or judgment.

A trade "followed" its playbook when no verified rule failed, no checklist item was answered "no", and nothing
is unknown or unanswered. It "broke" the playbook when any rule failed or any item was answered "no". Otherwise it
is "incomplete". Profit plays no part in any of this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

STOP_TOLERANCE_R = Decimal("-1.1")  # a stop-out a little beyond -1R (fees, slippage) still counts as respected


@dataclass(frozen=True)
class Rules:
    version_id: UUID
    version: int
    instruments: tuple[str, ...] = ()
    permitted_sessions: tuple[str, ...] = ()
    entry_hour_start: int | None = None
    entry_hour_end: int | None = None
    require_stop: bool = False
    max_risk_per_trade: Decimal | None = None
    min_reward_risk: Decimal | None = None
    max_trades_per_day: int | None = None
    pre_trade_checklist: tuple[tuple[str, str], ...] = ()  # (id, text)
    post_trade_checklist: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Facts:
    symbol: str
    status: str
    direction: str
    entry_session: str
    entry_hour: int  # market time
    entry_avg_price: Decimal
    planned_stop_price: Decimal | None
    planned_target_price: Decimal | None
    planned_risk_amount: Decimal | None
    initial_risk: Decimal | None
    r_multiple: Decimal | None
    trade_number_of_day: int  # 1-based, among this playbook's trades in the account on the session date


@dataclass(frozen=True)
class RuleResult:
    key: str
    label: str
    status: str  # pass | fail | unknown
    detail: str


@dataclass
class Assessment:
    version_id: UUID
    version: int
    rules: list[RuleResult] = field(default_factory=list)
    checklist: list[dict] = field(default_factory=list)  # {id, phase, text, answer: True/False/None}

    @property
    def outcome(self) -> str:
        if not self.rules and not self.checklist:
            return "no_rules"
        if any(r.status == "fail" for r in self.rules) or any(c["answer"] is False for c in self.checklist):
            return "broken"
        if any(r.status == "unknown" for r in self.rules) or any(c["answer"] is None for c in self.checklist):
            return "incomplete"
        return "followed"

    def as_dict(self) -> dict:
        return {
            "playbook_version_id": self.version_id,
            "version": self.version,
            "outcome": self.outcome,
            "verified": [r.__dict__ for r in self.rules],
            "checklist": self.checklist,
            "counts": {
                "verified_pass": sum(r.status == "pass" for r in self.rules),
                "verified_fail": sum(r.status == "fail" for r in self.rules),
                "verified_unknown": sum(r.status == "unknown" for r in self.rules),
                "checklist_yes": sum(c["answer"] is True for c in self.checklist),
                "checklist_no": sum(c["answer"] is False for c in self.checklist),
                "checklist_unanswered": sum(c["answer"] is None for c in self.checklist),
            },
        }


def _fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")


def evaluate_rules(f: Facts, r: Rules) -> list[RuleResult]:
    out: list[RuleResult] = []
    if r.instruments:
        allowed = {s.upper() for s in r.instruments}
        ok = f.symbol.upper() in allowed
        out.append(RuleResult("instrument", "Instrument allowed", "pass" if ok else "fail",
                              f"{f.symbol} {'is' if ok else 'is not'} in {', '.join(sorted(allowed))}"))  # fmt: skip
    if r.permitted_sessions:
        ok = f.entry_session in r.permitted_sessions
        out.append(RuleResult("session", "Session allowed", "pass" if ok else "fail",
                              f"Entered in {f.entry_session} hours; allowed: {', '.join(r.permitted_sessions)}"))  # fmt: skip
    if r.entry_hour_start is not None and r.entry_hour_end is not None:
        a, b, h = r.entry_hour_start, r.entry_hour_end, f.entry_hour
        ok = a <= h < b if a < b else (h >= a or h < b)  # windows may wrap past midnight
        out.append(RuleResult("entry_window", "Entry time window", "pass" if ok else "fail",
                              f"Entry hour {h:02d}:00 market time; window {a:02d}:00-{b:02d}:00"))  # fmt: skip
    if r.require_stop:
        ok = f.planned_stop_price is not None or f.planned_risk_amount is not None
        out.append(RuleResult("stop_set", "Initial stop recorded", "pass" if ok else "fail",
                              "Planned stop or risk amount recorded" if ok else "No planned stop or risk amount"))  # fmt: skip
    if r.max_risk_per_trade is not None:
        if f.initial_risk is None:
            out.append(RuleResult("max_risk", "Risk within limit", "unknown", "Initial risk unknown: record a stop"))
        else:
            ok = f.initial_risk <= r.max_risk_per_trade
            out.append(RuleResult("max_risk", "Risk within limit", "pass" if ok else "fail",
                                  f"Initial risk {_fmt(f.initial_risk)} vs limit {_fmt(r.max_risk_per_trade)}"))  # fmt: skip
    if r.min_reward_risk is not None:
        out.append(_reward_risk(f, r.min_reward_risk))
    if r.max_trades_per_day is not None:
        ok = f.trade_number_of_day <= r.max_trades_per_day
        out.append(RuleResult("max_trades", "Trades per day", "pass" if ok else "fail",
                              f"Trade #{f.trade_number_of_day} of the day; limit {r.max_trades_per_day}"))  # fmt: skip
    if r.require_stop or r.max_risk_per_trade is not None:
        if f.status != "closed" or f.r_multiple is None:
            out.append(RuleResult("stop_respected", "Loss within planned risk", "unknown",
                                  "Needs a closed trade with a known initial risk"))  # fmt: skip
        else:
            ok = f.r_multiple >= STOP_TOLERANCE_R
            out.append(RuleResult("stop_respected", "Loss within planned risk", "pass" if ok else "fail",
                                  f"Result {_fmt(f.r_multiple)}R (fails below {STOP_TOLERANCE_R}R)"))  # fmt: skip
    return out


def _reward_risk(f: Facts, minimum: Decimal) -> RuleResult:
    label = "Planned reward:risk"
    if f.planned_stop_price is None or f.planned_target_price is None:
        return RuleResult("reward_risk", label, "unknown", "Needs both a planned stop and a planned target")
    sign = 1 if f.direction == "long" else -1
    risk = sign * (f.entry_avg_price - f.planned_stop_price)
    reward = sign * (f.planned_target_price - f.entry_avg_price)
    if risk <= 0 or reward <= 0:
        return RuleResult("reward_risk", label, "fail", "Stop or target is on the wrong side of the entry")
    rr = (reward / risk).quantize(Decimal("0.01"))
    return RuleResult("reward_risk", label, "pass" if rr >= minimum else "fail",
                      f"Planned {_fmt(rr)}:1 vs minimum {_fmt(minimum)}:1")  # fmt: skip


def assess(f: Facts, r: Rules, answers: dict[str, bool]) -> Assessment:
    a = Assessment(r.version_id, r.version, evaluate_rules(f, r))
    for phase, items in (("pre", r.pre_trade_checklist), ("post", r.post_trade_checklist)):
        for item_id, text in items:
            a.checklist.append({"id": item_id, "phase": phase, "text": text, "answer": answers.get(item_id)})
    return a
