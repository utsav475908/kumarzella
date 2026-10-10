import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def expected(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def create_account(client, name="Main", **kw) -> dict:
    r = client.post("/api/v1/accounts", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, account_id: str, name: str, data: bytes | None = None):
    data = data if data is not None else fixture_bytes(name)
    return client.post("/api/v1/imports", data={"account_id": account_id}, files={"file": (name, data, "text/csv")})


def import_file(client, account_id: str, name: str, mapping: dict | None = None, options: dict | None = None,
                data: bytes | None = None) -> dict:  # fmt: skip
    up = upload(client, account_id, name, data)
    assert up.status_code == 201, up.text
    job = up.json()
    body = {"mapping": mapping or job["suggested_mapping"], "options": options or {}}
    pv = client.post(f"/api/v1/imports/{job['id']}/preview", json=body)
    assert pv.status_code == 200, pv.text
    cm = client.post(f"/api/v1/imports/{job['id']}/commit")
    return {"upload": job, "preview": pv.json(), "commit": cm}


def all_trades(client, **params) -> list[dict]:
    r = client.get("/api/v1/trades", params={"page_size": 500, "sort": "opened_at", "order": "asc", **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]
