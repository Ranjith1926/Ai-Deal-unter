"""Health endpoint tests. Dependency checks are patched, so no Postgres/Redis is needed."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import health
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"
    assert resp.headers["X-Request-ID"]


async def test_request_id_is_echoed(client):
    resp = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert resp.headers["X-Request-ID"] == "abc123"


async def test_database_ok(client, monkeypatch):
    async def ok() -> None: ...
    monkeypatch.setattr(health, "check_database", ok)
    assert (await client.get("/health/database")).status_code == 200


async def test_database_down_returns_503(client, monkeypatch):
    async def fail() -> None:
        raise ConnectionError("boom")
    monkeypatch.setattr(health, "check_database", fail)
    resp = await client.get("/health/database")
    assert resp.status_code == 503
    assert resp.json()["success"] is False


async def test_redis_down_returns_503(client, monkeypatch):
    async def fail() -> None:
        raise ConnectionError("boom")
    monkeypatch.setattr(health, "check_redis", fail)
    assert (await client.get("/health/redis")).status_code == 503
