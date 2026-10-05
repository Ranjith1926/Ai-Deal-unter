"""Hardening behaviour through the real API: unsafe links, login throttling, health, metrics, error hygiene."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.models import ProductPlatform, ProviderSyncLog
from app.services import catalog
from app.services.common import JobRun
from helpers import FakeRedis, ScriptedProvider, handle_for, pp, signup, PASSWORD


@pytest.fixture
def redis(client):
    from app.main import app

    app.state.redis = FakeRedis()
    return app.state.redis


# ------------------------------------------------------------------ unsafe provider links
async def test_unsafe_provider_urls_never_reach_the_database(factory, config):
    provider = ScriptedProvider("amazon", [
        pp("A1", "Good", brand="Acme", image_url="https://img.example/a.png"),
        pp("A2", "Evil link", brand="Acme"),
        pp("A3", "Evil image", brand="Acme", image_url="javascript:alert(1)"),
    ])
    provider.products[1] = provider.products[1].model_copy(update={"url": "javascript:alert(document.cookie)"})
    run = JobRun()
    await catalog.sync_catalog(factory, handle_for(provider), config, run)
    async with factory() as s:
        rows = {l.external_product_id: l for l in await s.scalars(select(ProductPlatform))}
    assert set(rows) == {"A1", "A3"} and run.errors == 1  # the listing with the bad link is refused outright
    async with factory() as s:
        from app.models import Product

        images = {p.name: p.image_url for p in await s.scalars(select(Product))}
    assert images["Good"] == "https://img.example/a.png" and images["Evil image"] is None


async def test_bad_links_already_stored_are_never_served(client, world, factory):
    async with factory() as s:
        await s.execute(update(ProductPlatform).where(ProductPlatform.id == world["amazon_tv_listing"]).values(url="javascript:alert(1)"))
        await s.execute(update(ProductPlatform).where(ProductPlatform.id == world["flipkart_tv_listing"]).values(affiliate_url="data:text/html,x"))
        await s.commit()
    card = (await client.get(f"/api/products/{world['tv']}")).json()["data"]
    assert all(not (p["buy_url"] or "").lower().startswith(("javascript:", "data:")) for p in card["platforms"])
    flip = next(p for p in card["platforms"] if p["platform"] == "flipkart")
    assert flip["is_affiliate_link"] is False and flip["buy_url"].startswith("https://flipkart.invalid")  # fell back to the plain URL
    amazon = next(p for p in card["platforms"] if p["platform"] == "amazon")
    assert amazon["buy_url"] is None
    compare = (await client.get(f"/api/products/{world['tv']}/compare")).json()["data"]["platforms"]
    assert all(not (p["buy_url"] or "").startswith("javascript:") for p in compare)
    r = await client.get(f"/api/products/{world['tv']}/buy?platform=amazon")
    assert r.status_code == 404


# ------------------------------------------------------------------ login throttling
async def wrong(client, email="victim@example.com", ip=None):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return await client.post("/api/auth/login", json={"email": email, "password": "wrong-password-1"}, headers=headers)


async def test_repeated_failures_lock_that_account_and_ip_for_a_while(client, redis, monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps, "_now", lambda: 5_000_000.0)
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 1000)  # isolate the per-account throttle
    await signup(client, "victim@example.com")
    codes = [(await wrong(client)).status_code for _ in range(5)]
    assert codes == [401] * 5
    blocked = await wrong(client)
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    # Even the right password is refused while locked, so the throttle really stops guessing.
    assert (await client.post("/api/auth/login", json={"email": "victim@example.com", "password": PASSWORD})).status_code == 429


async def test_other_accounts_and_correct_logins_are_not_slowed(client, redis, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 1000)
    await signup(client, "victim@example.com")
    await signup(client, "bystander@example.com")
    for _ in range(4):
        await wrong(client)  # one below the limit
    ok = await client.post("/api/auth/login", json={"email": "victim@example.com", "password": PASSWORD})
    assert ok.status_code == 200  # success is not blocked, and clears this IP's failure count
    assert (await wrong(client)).status_code == 401  # the counter restarted
    assert (await client.post("/api/auth/login", json={"email": "bystander@example.com", "password": PASSWORD})).status_code == 200


async def test_account_wide_limit_stops_distributed_guessing(client, redis, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 1000)
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", 1)  # let the test vary the client address
    await signup(client, "victim@example.com")
    # 20 failures from 20 different addresses (4x the per-IP limit) lock the account for everyone.
    for i in range(20):
        assert (await wrong(client, ip=f"203.0.113.{i}")).status_code == 401
    assert (await wrong(client, ip="198.51.100.77")).status_code == 429


async def test_spoofed_forwarded_for_cannot_bypass_limits_when_no_proxy_is_trusted(client, redis, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 1000)
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", 0)
    await signup(client, "victim@example.com")
    codes = [(await wrong(client, ip=f"203.0.113.{i}")).status_code for i in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]  # a fresh fake address each time changes nothing


async def test_login_throttle_does_not_log_anyone_out_when_redis_is_down(client, monkeypatch):
    from redis.exceptions import ConnectionError as RedisDown

    from app.main import app

    class Broken:
        async def get(self, *_):
            raise RedisDown("down")

        incr = expire = ttl = delete = get

    app.state.redis = Broken()
    await signup(client, "victim@example.com")
    assert (await client.post("/api/auth/login", json={"email": "victim@example.com", "password": PASSWORD})).status_code == 200


# ------------------------------------------------------------------ health
async def test_liveness_and_readiness(client, monkeypatch):
    from app.api import health

    async def up():
        return None

    # The shared pooled engine can be bound to an earlier test's event loop, so stub the probes here;
    # the real probes are exercised against live services in the Docker smoke checks.
    monkeypatch.setattr(health, "check_database", up)
    monkeypatch.setattr(health, "check_redis", up)
    assert (await client.get("/health/live")).json()["data"]["status"] == "ok"
    ready = await client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["data"]["status"] == "ready"


async def test_readiness_is_503_when_a_dependency_is_down(client, monkeypatch):
    from app.api import health

    async def down():
        raise ConnectionError("redis down")

    monkeypatch.setattr(health, "check_redis", down)
    r = await client.get("/health/ready")
    assert r.status_code == 503 and "redis" in r.json()["message"]


async def test_provider_health_reports_each_state_and_never_returns_an_error_status(client, factory):
    now = datetime.now(timezone.utc)
    async with factory() as s:
        s.add_all([
            ProviderSyncLog(provider="amazon", job_name="collect_prices", status="success", started_at=now - timedelta(minutes=20), completed_at=now - timedelta(minutes=19)),
            ProviderSyncLog(provider="flipkart", job_name="collect_prices", status="success", started_at=now - timedelta(hours=5), completed_at=now - timedelta(hours=5)),
        ])
        await s.commit()
    r = await client.get("/health/providers")
    data = r.json()["data"]
    states = {p["name"]: p["status"] for p in data["providers"]}
    assert r.status_code == 200 and states == {"amazon": "healthy", "flipkart": "stale"} and data["status"] == "degraded"

    async with factory() as s:
        s.add(ProviderSyncLog(provider="flipkart", job_name="collect_prices", status="failed", error_message="x", started_at=now, completed_at=now))
        await s.commit()
    assert {p["name"]: p["status"] for p in (await client.get("/health/providers")).json()["data"]["providers"]}["flipkart"] == "failing"


# ------------------------------------------------------------------ metrics
async def test_metrics_expose_request_and_business_series_without_leaking_ids(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "")
    await client.get(f"/api/products/{world['tv']}")
    await client.get(f"/api/products/{world['laptop_flat']}")
    await client.get("/api/does-not-exist")
    text = (await client.get("/metrics")).text
    assert 'dh_http_requests_total{method="GET",route="/api/products/{product_id}",status="200"}' in text
    assert f"/api/products/{world['tv']}" not in text and "does-not-exist" not in text  # route templates only
    assert 'route="unmatched"' in text
    for series in ("dh_http_request_duration_seconds_bucket", "dh_products_active", "dh_provider_last_success_age_seconds", "dh_price_alerts_active"):
        assert series in text


async def test_metrics_require_the_token_when_one_is_set(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "m" * 32)
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": f"Bearer {'m' * 32}"})).status_code == 200


async def test_metrics_are_off_in_production_without_a_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "")
    monkeypatch.setattr(get_settings(), "app_env", "production")
    assert (await client.get("/metrics")).status_code == 404


# ------------------------------------------------------------------ error hygiene & headers
async def test_unexpected_errors_never_leak_internals(client):
    from app.api.deps import get_session
    from app.main import app

    async def broken():
        raise RuntimeError("postgres://admin:hunter2@db/secret")
        yield  # pragma: no cover

    previous = app.dependency_overrides[get_session]
    app.dependency_overrides[get_session] = broken
    try:
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            r = await c.get("/api/products")
    finally:
        app.dependency_overrides[get_session] = previous
    assert r.status_code == 500 and r.json() == {"success": False, "data": None, "message": "Internal server error", "errors": []}
    assert "hunter2" not in r.text and "postgres" not in r.text and "Traceback" not in r.text


async def test_oversized_request_bodies_are_refused(client):
    r = await client.post("/api/auth/login", content=b"x" * 1_500_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["success"] is False


async def test_security_headers_on_every_response(client, world):
    for path in ("/api/products", "/api/nope", "/health/live"):
        h = (await client.get(path)).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
        assert h["cross-origin-resource-policy"] == "same-site" and "default-src 'none'" in h["content-security-policy"]
        assert "strict-transport-security" not in h  # only meaningful (and only sent) in production


async def test_passwords_and_tokens_are_never_logged(client, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    secret = "My-Very-Secret-Passphrase-99"
    await client.post("/api/auth/register", json={"email": "log@example.com", "name": "L", "password": secret})
    r = await client.post("/api/auth/login", json={"email": "log@example.com", "password": secret})
    token = r.json()["data"]["access_token"]
    refresh = r.json()["data"]["refresh_token"]
    await client.post("/api/auth/login", json={"email": "log@example.com", "password": "wrong-password-xyz"})
    logged = "\n".join(f"{rec.getMessage()} {rec.__dict__}" for rec in caplog.records)
    for sensitive in (secret, "wrong-password-xyz", token, refresh):
        assert sensitive not in logged
