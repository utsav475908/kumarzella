"""Versioned playbooks, per-trade adherence and checklists, trade annotations and advanced reports (API)."""

from decimal import Decimal as D

from tests.helpers import all_trades, create_account, import_file

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
RULES = {
    "instruments": ["aapl"],
    "require_stop": True,
    "entry_rules": "Break of the 5-minute opening range",
    "pre_trade_checklist": [{"text": "Waited for the opening range to complete"}],
    "post_trade_checklist": [{"text": "Screenshot saved"}],
}


def setup(client) -> tuple[dict, dict[str, dict]]:
    acct = create_account(client)
    import_file(client, acct["id"], "fixture_a.csv")
    r = client.post("/api/v1/playbooks", json={"name": "ORB", "rules": RULES})
    assert r.status_code == 201, r.text
    trades = {t["symbol"]: t for t in all_trades(client) if t["symbol"] in ("AAPL", "TSLA")}
    for t in trades.values():
        assert client.patch(f"/api/v1/trades/{t['id']}", json={"playbook_id": r.json()["id"]}).status_code == 200
    return r.json(), trades


def adherence(client, trade_id: str) -> dict:
    r = client.get(f"/api/v1/trades/{trade_id}/adherence")
    assert r.status_code == 200, r.text
    return r.json()["assessment"]


def checks(a: dict) -> dict[str, str]:
    return {x["key"]: x["status"] for x in a["verified"]}


def answer_all(client, trade_id: str, a: dict, value: bool = True):
    body = {"answers": [{"item_id": c["id"], "answer": value} for c in a["checklist"]]}
    r = client.put(f"/api/v1/trades/{trade_id}/checklist", json=body)
    assert r.status_code == 200, r.text
    return r.json()["assessment"]


def test_create_returns_first_version_with_checklist_ids(auth_client):
    r = auth_client.post("/api/v1/playbooks", json={"name": "ORB", "rules": RULES})
    pb = r.json()
    assert r.status_code == 201 and pb["current_version"] == 1
    assert pb["rules"]["instruments"] == ["AAPL"] and pb["rules"]["version"] == 1
    assert [v["change_note"] for v in pb["versions"]] == ["First version"]
    (item,) = pb["rules"]["pre_trade_checklist"]
    assert len(item["id"]) == 8 and item["text"] == RULES["pre_trade_checklist"][0]["text"]
    plain = auth_client.post("/api/v1/playbooks", json={"name": "Plain"}).json()
    assert plain["current_version"] == 1 and plain["rules"]["pre_trade_checklist"] == []
    bad = {"name": "Bad", "rules": {"entry_hour_start": 9}}
    assert auth_client.post("/api/v1/playbooks", json=bad).status_code == 422
    dup_ids = {"name": "Dup", "rules": {"pre_trade_checklist": [{"id": "x", "text": "a"}, {"id": "x", "text": "b"}]}}
    assert auth_client.post("/api/v1/playbooks", json=dup_ids).status_code == 422


def test_rule_checks_and_checklist_drive_the_outcome(auth_client):
    pb, trades = setup(auth_client)
    aapl, tsla = trades["AAPL"], trades["TSLA"]
    a = adherence(auth_client, aapl["id"])
    assert a["version"] == 1 and a["outcome"] == "broken"
    assert checks(a) == {"instrument": "pass", "stop_set": "fail", "stop_respected": "unknown"}
    # Record the stop: initial risk = |170.50 - 169| x 200 = 300, R = 145.85 / 300.
    auth_client.patch(f"/api/v1/trades/{aapl['id']}", json={"planned_stop_price": "169"})
    a = adherence(auth_client, aapl["id"])
    assert checks(a) == {"instrument": "pass", "stop_set": "pass", "stop_respected": "pass"}
    assert a["outcome"] == "incomplete" and a["counts"]["checklist_unanswered"] == 2
    assert answer_all(auth_client, aapl["id"], a)["outcome"] == "followed"
    assert answer_all(auth_client, aapl["id"], a, False)["outcome"] == "broken"
    clear = {"answers": [{"item_id": c["id"], "answer": None} for c in a["checklist"]]}
    assert auth_client.put(f"/api/v1/trades/{aapl['id']}/checklist", json=clear).json()["assessment"]["outcome"] == (
        "incomplete"
    )
    t = adherence(auth_client, tsla["id"])
    assert checks(t)["instrument"] == "fail" and t["outcome"] == "broken"

    unknown = {"answers": [{"item_id": "nope", "answer": True}]}
    r = auth_client.put(f"/api/v1/trades/{aapl['id']}/checklist", json=unknown)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_checklist_item"
    nvda = next(t for t in all_trades(auth_client) if t["symbol"] == "NVDA")
    assert auth_client.get(f"/api/v1/trades/{nvda['id']}/adherence").json()["assessment"] is None
    r = auth_client.put(f"/api/v1/trades/{nvda['id']}/checklist", json=unknown)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_playbook"


def test_new_version_never_rejudges_assigned_trades(auth_client):
    pb, trades = setup(auth_client)
    tsla = trades["TSLA"]
    r = auth_client.post(f"/api/v1/playbooks/{pb['id']}/versions",
                         json={**RULES, "instruments": ["AAPL", "TSLA"], "change_note": "Allow TSLA"})  # fmt: skip
    assert r.status_code == 201 and r.json()["version"] == 2
    detail = auth_client.get(f"/api/v1/playbooks/{pb['id']}").json()
    assert detail["current_version"] == 2 and [v["version"] for v in detail["versions"]] == [2, 1]
    assert detail["rules"]["instruments"] == ["AAPL", "TSLA"]
    v1 = auth_client.get(f"/api/v1/playbooks/{pb['id']}/versions/1").json()
    assert v1["instruments"] == ["AAPL"]
    assert auth_client.get(f"/api/v1/playbooks/{pb['id']}/versions/9").status_code == 404

    assert auth_client.get(f"/api/v1/trades/{tsla['id']}").json()["playbook_version"] == 1
    assert checks(adherence(auth_client, tsla["id"]))["instrument"] == "fail"  # still judged by version 1
    # Re-assigning the same playbook keeps the pin; removing and re-adding it pins the current version.
    auth_client.patch(f"/api/v1/trades/{tsla['id']}", json={"playbook_id": pb["id"]})
    assert adherence(auth_client, tsla["id"])["version"] == 1
    auth_client.patch(f"/api/v1/trades/{tsla['id']}", json={"playbook_id": None})
    assert auth_client.get(f"/api/v1/trades/{tsla['id']}").json()["playbook_version_id"] is None
    auth_client.patch(f"/api/v1/trades/{tsla['id']}", json={"playbook_id": pb["id"]})
    a = adherence(auth_client, tsla["id"])
    assert a["version"] == 2 and checks(a)["instrument"] == "pass"


def test_checklist_answers_belong_to_the_pinned_version(auth_client):
    pb, trades = setup(auth_client)
    aapl = trades["AAPL"]
    a = adherence(auth_client, aapl["id"])
    answer_all(auth_client, aapl["id"], a)
    # Version 2 keeps the pre-trade item (same id) and drops the post-trade one.
    pre = a["checklist"][0]
    auth_client.post(f"/api/v1/playbooks/{pb['id']}/versions",
                     json={**RULES, "pre_trade_checklist": [{"id": pre["id"], "text": pre["text"]}],
                           "post_trade_checklist": []})  # fmt: skip
    auth_client.patch(f"/api/v1/trades/{aapl['id']}", json={"playbook_id": None})
    auth_client.patch(f"/api/v1/trades/{aapl['id']}", json={"playbook_id": pb["id"]})
    a2 = adherence(auth_client, aapl["id"])
    assert a2["version"] == 2 and [c["answer"] for c in a2["checklist"]] == [None]  # old answers don't carry over


def test_reports_and_playbook_adherence(auth_client):
    pb, trades = setup(auth_client)
    aapl = trades["AAPL"]
    auth_client.patch(f"/api/v1/trades/{aapl['id']}", json={"planned_stop_price": "169"})
    answer_all(auth_client, aapl["id"], adherence(auth_client, aapl["id"]))
    r = auth_client.get("/api/v1/analytics/reports")
    assert r.status_code == 200, r.text
    rep = r.json()
    orb, none = rep["playbooks"]
    assert orb["label"] == "ORB" and orb["closed_trades"] == 2 and D(orb["net_pnl"]) == D("-56.15")
    assert orb["adherence"] == {"followed": 1, "broken": 1, "incomplete": 0, "no_rules": 0}
    assert D(orb["followed_rate"]) == D("0.5")
    assert none["label"] == "No playbook" and none["closed_trades"] == 3 and none["adherence"] is None
    adh = rep["adherence"]
    assert adh["counts"]["followed"] == 1 and adh["unassessed_trades"] == 3
    inst = next(x for x in adh["rules"] if x["key"] == "instrument")
    assert (inst["passed"], inst["failed"], D(inst["net_pnl_when_failed"])) == (1, 1, D("-202"))
    assert [b["symbol"] for b in adh["broken_trades"]] == ["TSLA"]
    assert "not whether it made money" in adh["note"]
    assert sum(b["closed_trades"] for b in rep["by_holding_time"]) == 5
    assert [m["key"] for m in rep["by_month"]] == ["2024-03"]
    es = next(c for c in rep["costs_by_symbol"] if c["symbol"] == "ESH4")
    assert D(es["total_fees"]) == D("8.40") and es["trades"] == 2

    scoped = auth_client.get(f"/api/v1/playbooks/{pb['id']}/adherence").json()
    assert scoped["counts"]["followed"] == 1 and scoped["assessed_trades"] == 2
    assert scoped["filters"]["playbook_id"] == [pb["id"]]


def test_trade_annotations(auth_client):
    _, trades = setup(auth_client)
    tid = trades["AAPL"]["id"]
    url = f"/api/v1/trades/{tid}/annotations"
    r = auth_client.post(url, json={"bar_time": "2024-03-04T14:40:00Z", "price": "171.2", "kind": "mistake",
                                    "text": "Added without confirmation"})  # fmt: skip
    assert r.status_code == 201, r.text
    assert auth_client.post(url, json={"bar_time": "2024-03-04T14:30:00Z", "text": " Range high "}).status_code == 201
    notes = auth_client.get(url).json()
    assert [n["text"] for n in notes] == ["Range high", "Added without confirmation"]
    assert notes[1]["kind"] == "mistake" and D(notes[1]["price"]) == D("171.2")
    far = auth_client.post(url, json={"bar_time": "2024-04-01T00:00:00Z", "text": "x"})
    assert far.status_code == 422 and far.json()["error"]["code"] == "annotation_out_of_range"
    assert auth_client.post(url, json={"bar_time": "2024-03-04T14:40:00", "text": "naive"}).status_code == 422
    assert auth_client.post(url, json={"bar_time": "2024-03-04T14:40:00Z", "text": "x", "kind": "?"}).status_code == 422
    assert auth_client.delete(f"{url}/{notes[0]['id']}").status_code == 204
    assert len(auth_client.get(url).json()) == 1


def test_playbook_screenshots(auth_client):
    pb = auth_client.post("/api/v1/playbooks", json={"name": "ORB"}).json()
    url = f"/api/v1/playbooks/{pb['id']}/attachments"
    r = auth_client.post(url, files={"file": ("setup.png", PNG, "image/png")})
    assert r.status_code == 201 and r.json()["content_type"] == "image/png"
    assert auth_client.post(url, files={"file": ("x.png", b"%PDF-1.4 fake", "image/png")}).status_code == 422
    (att,) = auth_client.get(f"/api/v1/playbooks/{pb['id']}").json()["attachments"]
    got = auth_client.get(f"/api/v1/attachments/{att['id']}/content")
    assert got.status_code == 200 and got.content == PNG
    assert auth_client.delete(f"/api/v1/attachments/{att['id']}").status_code == 204
    assert auth_client.get(f"/api/v1/playbooks/{pb['id']}").json()["attachments"] == []


def test_journal_follows_trade_when_reconstruction_replaces_it(auth_client):
    pb, trades = setup(auth_client)
    aapl = trades["AAPL"]
    a = adherence(auth_client, aapl["id"])
    answer_all(auth_client, aapl["id"], a)
    auth_client.post(f"/api/v1/trades/{aapl['id']}/annotations", json={"bar_time": "2024-03-04T14:40:00Z", "text": "n"})
    # An earlier manual sell turns A1+A2 into the cover of a short, so the original AAPL trade is replaced.
    r = auth_client.post("/api/v1/trades/manual", json={
        "account_id": aapl["account_id"], "symbol": "AAPL",
        "executions": [{"side": "sell", "quantity": "200", "price": "171", "executed_at": "2024-03-04T14:30:00Z"}],
    })  # fmt: skip
    assert r.status_code == 201, r.text
    after = [t for t in all_trades(auth_client) if t["symbol"] == "AAPL"]
    assert aapl["id"] not in {t["id"] for t in after}
    successor = next(t for t in after if t["playbook_id"] == pb["id"])
    assert successor["playbook_version"] == 1
    moved = adherence(auth_client, successor["id"])
    assert [c["answer"] for c in moved["checklist"]] == [True, True]
    assert [n["text"] for n in auth_client.get(f"/api/v1/trades/{successor['id']}/annotations").json()] == ["n"]


def test_review_endpoints_are_owner_only(auth_client, other_client):
    pb, trades = setup(auth_client)
    tid = trades["AAPL"]["id"]
    note = auth_client.post(f"/api/v1/trades/{tid}/annotations", json={"bar_time": "2024-03-04T14:40:00Z", "text": "n"})
    answers = {"answers": [{"item_id": "x", "answer": True}]}
    assert other_client.get(f"/api/v1/trades/{tid}/adherence").status_code == 404
    assert other_client.put(f"/api/v1/trades/{tid}/checklist", json=answers).status_code == 404
    assert other_client.get(f"/api/v1/trades/{tid}/annotations").status_code == 404
    assert other_client.post(f"/api/v1/trades/{tid}/annotations", json={"bar_time": "2024-03-04T14:40:00Z",
                                                                         "text": "x"}).status_code == 404  # fmt: skip
    assert other_client.delete(f"/api/v1/trades/{tid}/annotations/{note.json()['id']}").status_code == 404
    assert other_client.get(f"/api/v1/playbooks/{pb['id']}/versions/1").status_code == 404
    assert other_client.post(f"/api/v1/playbooks/{pb['id']}/versions", json=RULES).status_code == 404
    assert other_client.get(f"/api/v1/playbooks/{pb['id']}/adherence").status_code == 404
    assert other_client.post(f"/api/v1/playbooks/{pb['id']}/attachments",
                             files={"file": ("a.png", PNG, "image/png")}).status_code == 404  # fmt: skip
    rep = other_client.get("/api/v1/analytics/reports").json()
    assert rep["playbooks"] == [] and rep["adherence"]["assessed_trades"] == 0
    # Another user's playbook can't be assigned to your trade.
    theirs = other_client.post("/api/v1/playbooks", json={"name": "Theirs"}).json()
    assert auth_client.patch(f"/api/v1/trades/{tid}", json={"playbook_id": theirs["id"]}).status_code == 422


def test_export_includes_versions_answers_and_annotations(auth_client):
    _, trades = setup(auth_client)
    tid = trades["AAPL"]["id"]
    answer_all(auth_client, tid, adherence(auth_client, tid))
    auth_client.post(f"/api/v1/trades/{tid}/annotations", json={"bar_time": "2024-03-04T14:40:00Z", "text": "n"})
    exp = auth_client.get("/api/v1/exports/me").json()
    assert len(exp["playbook_versions"]) == 1 and len(exp["trade_checklist_answers"]) == 2
    assert len(exp["trade_annotations"]) == 1
