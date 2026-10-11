"""Rule-adherence evaluation: each verified rule, checklist handling and the outcome logic (pure functions)."""

from decimal import Decimal as D
from uuid import uuid4

from app.modules.analytics import adherence as ad
from app.modules.analytics import reports
from app.modules.analytics.metrics import TradeRow

FACTS = ad.Facts(
    symbol="AAPL", status="closed", direction="long", entry_session="regular", entry_hour=9,
    entry_avg_price=D("100"), planned_stop_price=D("99"), planned_target_price=D("103"), planned_risk_amount=None,
    initial_risk=D("100"), r_multiple=D("-0.5"), trade_number_of_day=1,
)  # fmt: skip


def rules(**kw) -> ad.Rules:
    return ad.Rules(version_id=uuid4(), version=1, **kw)


def statuses(f: ad.Facts, r: ad.Rules) -> dict[str, str]:
    return {x.key: x.status for x in ad.evaluate_rules(f, r)}


def with_(**kw) -> ad.Facts:
    return ad.Facts(**(FACTS.__dict__ | kw))


def test_no_rules_means_no_checks():
    a = ad.assess(FACTS, rules(), {})
    assert a.rules == [] and a.outcome == "no_rules"


def test_instrument_session_and_window():
    r = rules(instruments=("aapl", "MSFT"), permitted_sessions=("regular",), entry_hour_start=9, entry_hour_end=11)
    assert statuses(FACTS, r) == {"instrument": "pass", "session": "pass", "entry_window": "pass"}
    bad = with_(symbol="TSLA", entry_session="extended", entry_hour=11)
    assert statuses(bad, r) == {"instrument": "fail", "session": "fail", "entry_window": "fail"}
    overnight = rules(entry_hour_start=22, entry_hour_end=2)  # wraps past midnight
    assert statuses(with_(entry_hour=23), overnight)["entry_window"] == "pass"
    assert statuses(with_(entry_hour=1), overnight)["entry_window"] == "pass"
    assert statuses(with_(entry_hour=2), overnight)["entry_window"] == "fail"


def test_stop_risk_and_stop_respected():
    r = rules(require_stop=True, max_risk_per_trade=D("100"))
    assert statuses(FACTS, r) == {"stop_set": "pass", "max_risk": "pass", "stop_respected": "pass"}
    assert statuses(with_(initial_risk=D("100.01")), r)["max_risk"] == "fail"
    no_stop = with_(planned_stop_price=None, initial_risk=None, r_multiple=None)
    assert statuses(no_stop, r) == {"stop_set": "fail", "max_risk": "unknown", "stop_respected": "unknown"}
    assert statuses(with_(planned_stop_price=None, planned_risk_amount=D("50")), r)["stop_set"] == "pass"
    assert statuses(with_(r_multiple=D("-1.1")), r)["stop_respected"] == "pass"  # small overshoot tolerated
    assert statuses(with_(r_multiple=D("-1.11")), r)["stop_respected"] == "fail"
    assert statuses(with_(status="open"), r)["stop_respected"] == "unknown"


def test_reward_risk_both_directions():
    r = rules(min_reward_risk=D("3"))
    assert statuses(FACTS, r)["reward_risk"] == "pass"  # (103 - 100) / (100 - 99) = 3
    assert statuses(with_(planned_target_price=D("102.99")), r)["reward_risk"] == "fail"
    short = with_(direction="short", planned_stop_price=D("101"), planned_target_price=D("97"))
    assert statuses(short, r)["reward_risk"] == "pass"
    wrong_side = with_(direction="short")  # stop below entry on a short
    (res,) = ad.evaluate_rules(wrong_side, r)
    assert res.status == "fail" and "wrong side" in res.detail
    assert statuses(with_(planned_target_price=None), r)["reward_risk"] == "unknown"


def test_trades_per_day():
    r = rules(max_trades_per_day=2)
    assert statuses(with_(trade_number_of_day=2), r)["max_trades"] == "pass"
    assert statuses(with_(trade_number_of_day=3), r)["max_trades"] == "fail"


def test_outcome_combines_rules_and_checklist_without_profit():
    r = rules(instruments=("AAPL",), pre_trade_checklist=(("a", "Waited for confirmation"),),
              post_trade_checklist=(("b", "Logged the trade"),))  # fmt: skip
    assert ad.assess(FACTS, r, {}).outcome == "incomplete"
    assert ad.assess(FACTS, r, {"a": True}).outcome == "incomplete"
    assert ad.assess(FACTS, r, {"a": True, "b": True}).outcome == "followed"
    assert ad.assess(FACTS, r, {"a": False, "b": True}).outcome == "broken"
    assert ad.assess(with_(symbol="TSLA"), r, {"a": True, "b": True}).outcome == "broken"
    # A big winner that broke a rule is still broken; a loser that followed every rule is still followed.
    assert ad.assess(with_(symbol="TSLA", r_multiple=D("5")), r, {"a": True, "b": True}).outcome == "broken"
    assert ad.assess(with_(r_multiple=D("-1")), r, {"a": True, "b": True}).outcome == "followed"
    d = ad.assess(FACTS, r, {"a": False}).as_dict()
    assert d["counts"] == {"verified_pass": 1, "verified_fail": 0, "verified_unknown": 0, "checklist_yes": 0,
                           "checklist_no": 1, "checklist_unanswered": 1}  # fmt: skip


def _row(net: str, r: str | None = None, pb=None, seconds: int = 60) -> TradeRow:
    from datetime import UTC, date, datetime

    t = datetime(2024, 3, 4, 15, tzinfo=UTC)
    return TradeRow(id=uuid4(), account_id=uuid4(), symbol="AAPL", asset_class="stock", direction="long",
                    opened_at=t, closed_at=t, session_date=date(2024, 3, 4), entry_session="regular", entry_hour=10,
                    gross_pnl=D(net), fees=D(0), net_pnl=D(net), holding_seconds=seconds,
                    r_multiple=D(r) if r else None, playbook_id=pb, playbook_name="ORB" if pb else None)  # fmt: skip


def test_report_groups_by_outcome_rule_and_item():
    pb = uuid4()
    r = rules(instruments=("AAPL",), require_stop=True, pre_trade_checklist=(("a", "Confirmation"),))
    followed, broken, incomplete, plain = _row("50", "0.5", pb), _row("200", "2", pb), _row("-30", None, pb), _row("10")
    fx = ad.Facts(**(FACTS.__dict__ | {"r_multiple": D("0.5")}))
    assessments = {
        followed.id: ad.assess(fx, r, {"a": True}),
        broken.id: ad.assess(fx, r, {"a": False}),
        incomplete.id: ad.assess(with_(r_multiple=None, status="open"), r, {"a": True}),
    }
    out = reports.adherence([followed, broken, incomplete, plain], assessments)
    assert out["counts"] == {"followed": 1, "broken": 1, "incomplete": 1, "no_rules": 0}
    assert out["assessed_trades"] == 3 and out["unassessed_trades"] == 1
    assert out["followed_rate"] == D("0.5")  # 1 / (1 + 1); incomplete is left out
    groups = {g["outcome"]: g for g in out["outcomes"]}
    assert groups["broken"]["net_pnl"] == D("200.00") and groups["followed"]["net_pnl"] == D("50.00")
    (item,) = out["checklist"]
    assert (item["yes"], item["no"], item["net_pnl_when_no"]) == (2, 1, D("200.00"))
    stop = next(x for x in out["rules"] if x["key"] == "stop_respected")
    assert (stop["passed"], stop["unknown"]) == (2, 1)
    (b,) = out["broken_trades"]
    assert b["trade_id"] == broken.id and b["checklist_no"] == ["Confirmation"] and b["failed_rules"] == []
    cmp = reports.playbook_comparison([followed, broken, incomplete, plain], assessments)
    assert [g["label"] for g in cmp] == ["ORB", "No playbook"]
    assert cmp[0]["adherence"]["followed"] == 1 and cmp[1]["adherence"] is None


def test_holding_buckets():
    assert [reports.holding_bucket(s) for s in (0, 59, 60, 3599, 3600, 86399, 86400, 10**7)] == [
        "< 1 min", "< 1 min", "1-5 min", "15-60 min", "1-4 h", "4-24 h", "1-5 days", "> 5 days",
    ]  # fmt: skip
