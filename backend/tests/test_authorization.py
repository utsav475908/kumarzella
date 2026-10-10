"""Tenant isolation: another user must never read or modify someone else's records."""

from tests.helpers import all_trades, create_account, import_file, upload


def _setup(auth_client):
    acct = create_account(auth_client)
    res = import_file(auth_client, acct["id"], "fixture_a.csv")
    trade = all_trades(auth_client)[0]
    tag = auth_client.post("/api/v1/tags", json={"name": "Mine"}).json()
    pb = auth_client.post("/api/v1/playbooks", json={"name": "Mine"}).json()
    return acct, res["upload"], trade, tag, pb


def test_other_user_cannot_read_anything(auth_client, other_client):
    acct, job, trade, tag, pb = _setup(auth_client)
    assert other_client.get(f"/api/v1/accounts/{acct['id']}").status_code == 404
    assert other_client.get(f"/api/v1/imports/{job['id']}").status_code == 404
    assert other_client.get(f"/api/v1/imports/{job['id']}/records").status_code == 404
    assert other_client.get(f"/api/v1/trades/{trade['id']}").status_code == 404
    assert other_client.get(f"/api/v1/playbooks/{pb['id']}").status_code == 404
    assert other_client.get("/api/v1/trades").json()["total"] == 0
    assert other_client.get("/api/v1/trades", params={"account_id": acct["id"]}).json()["total"] == 0
    assert other_client.get("/api/v1/tags").json() == []
    assert other_client.get("/api/v1/imports").json()["total"] == 0


def test_other_user_cannot_modify_anything(auth_client, other_client):
    acct, job, trade, tag, pb = _setup(auth_client)
    assert other_client.patch(f"/api/v1/trades/{trade['id']}", json={"rating": 1}).status_code == 404
    assert other_client.post(f"/api/v1/trades/{trade['id']}/notes", json={"body": "x"}).status_code == 404
    assert other_client.patch(f"/api/v1/accounts/{acct['id']}", json={"name": "pwned"}).status_code == 404
    assert other_client.delete(f"/api/v1/accounts/{acct['id']}", params={"confirm_name": "Main"}).status_code == 404
    assert other_client.post(f"/api/v1/imports/{job['id']}/commit").status_code == 404
    assert upload(other_client, acct["id"], "fixture_a.csv").status_code == 404
    assert other_client.delete(f"/api/v1/tags/{tag['id']}").status_code == 404
    r = other_client.post(
        "/api/v1/trades/manual",
        json={"account_id": acct["id"], "symbol": "X", "executions": [
            {"side": "buy", "quantity": "1", "price": "1", "executed_at": "2024-01-01T00:00:00Z"}]},
    )  # fmt: skip
    assert r.status_code == 404
    assert (
        other_client.post(
            f"/api/v1/trades/{trade['id']}/attachments", files={"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")}
        ).status_code
        == 404
    )


def test_cannot_attach_foreign_tag_or_playbook(auth_client, other_client):
    _, _, _, tag, pb = _setup(auth_client)
    oacct = create_account(other_client, name="O")
    import_file(other_client, oacct["id"], "fixture_no_ids.csv")
    (otrade,) = all_trades(other_client)
    r = other_client.patch(f"/api/v1/trades/{otrade['id']}", json={"tag_ids": [tag["id"]]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_tag"
    r = other_client.patch(f"/api/v1/trades/{otrade['id']}", json={"playbook_id": pb["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_playbook"


def test_unauthenticated_requests_rejected(client):
    for path in ("/api/v1/accounts", "/api/v1/trades", "/api/v1/imports", "/api/v1/tags", "/api/v1/exports/me"):
        assert client.get(path).status_code == 401


def test_database_rejects_cross_tenant_rows(auth_client, other_client, db):
    """Composite foreign keys make cross-tenant rows impossible even if application code had a bug."""
    import uuid

    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.modules.journal.models import TradeTag

    _, _, trade, _, _ = _setup(auth_client)
    otag = other_client.post("/api/v1/tags", json={"name": "Theirs"}).json()
    other_user = other_client.get("/api/v1/auth/me").json()
    db.add(TradeTag(trade_id=uuid.UUID(trade["id"]), tag_id=uuid.UUID(otag["id"]), user_id=uuid.UUID(other_user["id"])))
    with pytest.raises(IntegrityError):
        db.commit()
