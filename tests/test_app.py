from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import app

KEY = "practice-test-key-32-characters-long"
PAYLOAD = {"product": "Keyboard", "quantity": 2, "unit_price_paise": 150000}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", KEY)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "orders.db"))
    with TestClient(app) as connection:
        yield connection


def headers(key="test-order-001"):
    return {"X-API-Key": KEY, "Idempotency-Key": key}


def test_health_and_version(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/version").json() == {"version": "local"}


def test_authentication(client):
    assert client.get("/orders").status_code == 401
    assert client.get("/orders", headers={"X-API-Key": "wrong"}).status_code == 401


def test_create_read_cancel(client):
    result = client.post("/orders", json=PAYLOAD, headers=headers())
    assert result.status_code == 201
    assert result.json()["total_paise"] == 300000
    assert result.headers["X-Request-ID"]
    url = "/orders/" + result.json()["id"]
    assert client.get(url, headers=headers()).json()["status"] == "pending"
    assert client.post(url + "/cancel", headers=headers()).json()["status"] == "cancelled"
    assert client.post(url + "/cancel", headers=headers()).status_code == 200


def test_idempotent_retry_and_conflict(client):
    first = client.post("/orders", json=PAYLOAD, headers=headers())
    retry = client.post("/orders", json=PAYLOAD, headers=headers())
    assert retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"]
    conflict = client.post("/orders", json={**PAYLOAD, "quantity": 3}, headers=headers())
    assert conflict.status_code == 409


def test_concurrent_retries(client):
    def create(_):
        return client.post("/orders", json=PAYLOAD, headers=headers("concurrent-order"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(8)))
    assert sum(r.status_code == 201 for r in results) == 1
    assert len({r.json()["id"] for r in results}) == 1


@pytest.mark.parametrize("field,value", [("quantity", 0), ("quantity", -1),
                                         ("quantity", "2"), ("product", " "),
                                         ("unit_price_paise", 0)])
def test_invalid_input(client, field, value):
    assert client.post("/orders", json={**PAYLOAD, field: value}, headers=headers()).status_code == 422


def test_missing_idempotency_key(client):
    assert client.post("/orders", json=PAYLOAD, headers={"X-API-Key": KEY}).status_code == 422


def test_missing_order(client):
    assert client.get("/orders/missing", headers=headers()).status_code == 404
    assert client.post("/orders/missing/cancel", headers=headers()).status_code == 404


def test_pagination(client):
    for index in range(3):
        client.post("/orders", json=PAYLOAD, headers=headers(f"page-key-{index}"))
    data = client.get("/orders?limit=2&offset=1", headers=headers()).json()
    assert len(data["items"]) == 2
    assert client.get("/orders?limit=101", headers=headers()).status_code == 422


def test_database_persists_across_app_restart(client):
    order_id = client.post("/orders", json=PAYLOAD, headers=headers()).json()["id"]
    with TestClient(app) as restarted:
        assert restarted.get("/orders/" + order_id, headers=headers()).status_code == 200


def test_readiness_detects_missing_schema(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "empty.db"))
    assert client.get("/health/ready").status_code == 503


def test_startup_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API_KEY"):
        with TestClient(app):
            pass
