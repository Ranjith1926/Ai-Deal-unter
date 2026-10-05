import re
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.engine.config import ScoringConfig
from app.models import Notification, RefreshToken

from helpers import PASSWORD, FakeRedis, signup


async def test_register_returns_envelope_and_no_password(client):
    r = await client.post("/api/auth/register", json={"email": "New@Example.com", "name": " Asha ", "password": PASSWORD})
    body = r.json()
    assert r.status_code == 201 and body["success"] is True and body["errors"] == []
    assert body["data"]["email"] == "new@example.com" and body["data"]["name"] == "Asha"
    assert "password" not in str(body).lower().replace("password updated", "")
    assert r.headers["cache-control"] == "no-store"


async def test_duplicate_email_conflicts_case_insensitively(client):
    await signup(client, "dup@example.com")
    r = await client.post("/api/auth/register", json={"email": "DUP@example.com", "name": "x", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["success"] is False


@pytest.mark.parametrize("password", ["short", "password123", "x" * 129])
async def test_weak_passwords_rejected(client, password):
    r = await client.post("/api/auth/register", json={"email": "a@example.com", "name": "A", "password": password})
    assert r.status_code == 422 and r.json()["errors"]


async def test_invalid_email_is_a_validation_error(client):
    r = await client.post("/api/auth/register", json={"email": "not-an-email", "name": "A", "password": PASSWORD})
    assert r.status_code == 422
    assert any(e.startswith("email") for e in r.json()["errors"])


async def test_login_errors_are_generic(client):
    await signup(client, "real@example.com")
    wrong = await client.post("/api/auth/login", json={"email": "real@example.com", "password": "wrong-password-1"})
    unknown = await client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "wrong-password-1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"] == "Invalid email or password"


async def test_protected_routes_need_a_valid_token(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me", headers={"Authorization": "Bearer garbage"})).status_code == 401
    _, headers = await signup(client)
    r = await client.get("/api/me", headers=headers)
    assert r.status_code == 200 and r.json()["data"]["email"] == "shopper@example.com"


async def test_expired_token_rejected(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.core.security import create_access_token

    await signup(client)
    token, _ = create_access_token(1, datetime.now(timezone.utc) - timedelta(hours=2))
    r = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["message"].lower()


async def test_refresh_rotates_and_reuse_revokes_everything(client, factory):
    tokens, _ = await signup(client)
    first = tokens["refresh_token"]
    r = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200
    second = r.json()["data"]["refresh_token"]
    assert second != first

    # An immediate replay (a parallel request) is benign: it gets its own fresh pair, nothing is revoked...
    parallel = await client.post("/api/auth/refresh", json={"refresh_token": first})
    assert parallel.status_code == 200 and parallel.json()["data"]["refresh_token"] not in (first, second)
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))) == 3
        assert await s.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.rotated_at.is_not(None))) == 1

    # ...whereas replaying it later means it may have been stolen: every session is revoked.
    async with factory() as s:
        row = await s.scalar(select(RefreshToken).where(RefreshToken.rotated_at.is_not(None)))
        row.rotated_at = row.rotated_at - timedelta(minutes=5)
        await s.commit()
    assert (await client.post("/api/auth/refresh", json={"refresh_token": first})).status_code == 401
    assert (await client.post("/api/auth/refresh", json={"refresh_token": second})).status_code == 401
    assert (await client.post("/api/auth/refresh", json={"refresh_token": parallel.json()["data"]["refresh_token"]})).status_code == 401
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))) == 0


async def test_revoked_tokens_stay_dead_even_inside_the_rotation_leeway(client):
    tokens, headers = await signup(client)
    await client.post("/api/auth/change-password", headers=headers,
                      json={"current_password": PASSWORD, "new_password": "another-long-passphrase"})
    # The token was revoked just now - there is no leeway for explicit revocation.
    assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401


async def test_logout_revokes_refresh_token(client):
    tokens, _ = await signup(client)
    assert (await client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]})).status_code == 200
    assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    # Logging out an unknown token is harmless.
    assert (await client.post("/api/auth/logout", json={"refresh_token": "x" * 40})).status_code == 200


async def test_password_reset_flow(client, factory):
    tokens, _ = await signup(client, "reset@example.com")
    r = await client.post("/api/auth/password-reset/request", json={"email": "reset@example.com"})
    assert r.status_code == 200
    async with factory() as s:
        note = await s.scalar(select(Notification).where(Notification.type == "email"))
    token = re.search(r"token=([\w-]+)", note.message).group(1)

    new_password = "a-brand-new-passphrase"
    r = await client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": new_password})
    assert r.status_code == 200
    # Old password and old sessions are dead; the new password works; the link is single-use.
    assert (await client.post("/api/auth/login", json={"email": "reset@example.com", "password": PASSWORD})).status_code == 401
    assert (await client.post("/api/auth/login", json={"email": "reset@example.com", "password": new_password})).status_code == 200
    assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    assert (await client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": new_password})).status_code == 422


async def test_password_reset_does_not_reveal_whether_account_exists(client, factory):
    real = await client.post("/api/auth/password-reset/request", json={"email": "nobody@example.com"})
    await signup(client, "exists@example.com")
    known = await client.post("/api/auth/password-reset/request", json={"email": "exists@example.com"})
    assert real.status_code == known.status_code == 200 and real.json()["message"] == known.json()["message"]
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Notification)) == 1  # only the real account


async def test_reset_with_bad_token_or_weak_password(client):
    r = await client.post("/api/auth/password-reset/confirm", json={"token": "n" * 40, "new_password": "whatever-long-enough"})
    assert r.status_code == 422


async def test_change_password(client):
    tokens, headers = await signup(client, "chg@example.com")
    bad = await client.post("/api/auth/change-password", headers=headers,
                            json={"current_password": "nope-nope-nope", "new_password": "another-long-passphrase"})
    assert bad.status_code == 401
    ok = await client.post("/api/auth/change-password", headers=headers,
                           json={"current_password": PASSWORD, "new_password": "another-long-passphrase"})
    assert ok.status_code == 200
    assert (await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401


async def test_auth_endpoints_are_rate_limited(client, monkeypatch):
    from app.api import deps
    from app.core.config import get_settings
    from app.main import app

    monkeypatch.setattr(deps, "_now", lambda: 1_000_000.0)  # pin the window so it cannot roll over mid-test

    app.state.redis = FakeRedis()
    settings = get_settings()
    original = settings.auth_rate_limit_per_minute
    settings.auth_rate_limit_per_minute = 3
    try:
        codes = [
            (await client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-password-1"})).status_code
            for _ in range(5)
        ]
        blocked = await client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-password-1"})
    finally:
        settings.auth_rate_limit_per_minute = original
    assert codes == [401, 401, 401, 429, 429]
    assert blocked.status_code == 429 and blocked.json()["success"] is False and int(blocked.headers["retry-after"]) >= 1


async def test_unknown_route_uses_error_envelope_and_security_headers(client):
    r = await client.get("/api/nope", headers={"X-Request-ID": "trace-123"})
    assert r.status_code == 404 and r.json()["success"] is False
    assert r.headers["x-request-id"] == "trace-123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]
