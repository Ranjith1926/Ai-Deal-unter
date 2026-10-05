"""Production safety checks, URL sanitising, proxy-aware client IPs and body limits (no database needed)."""
import subprocess
import sys

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.config import Settings
from app.core.hardening import BodySizeLimitMiddleware, client_ip, hash_subject, production_problems
from app.core.urls import MAX_URL_LENGTH, UnsafeUrlError, require_http_url, safe_http_url

GOOD = dict(
    app_env="production",
    jwt_secret="q7Lx9vT2mZp4Rk8nWb3YdH6sFa1JcE5u",
    database_url="postgresql+asyncpg://dealhunter:Zr4nQ8vL2xTb7KmW@postgres:5432/dealhunter",
    cors_origins="https://deals.example.com",
    frontend_url="https://deals.example.com",
    # Pinned so the developer's own .env (e.g. a local mail catcher) cannot change the outcome.
    smtp_host="smtp.example.com",
    smtp_security="starttls",
    vapid_subject="mailto:ops@example.com",
)


def prod(**over) -> Settings:
    return Settings(**{**GOOD, **over})


# ------------------------------------------------------------------ production configuration checks
def test_a_correct_production_config_has_no_problems():
    assert production_problems(prod()) == []


def test_development_is_never_blocked():
    assert production_problems(Settings(app_env="development", jwt_secret="")) == []


@pytest.mark.parametrize("over,needle", [
    ({"jwt_secret": ""}, "JWT_SECRET must be at least 32"),
    ({"jwt_secret": "short"}, "JWT_SECRET must be at least 32"),
    ({"jwt_secret": "change-me-change-me-change-me-change-me"}, "placeholder"),
    ({"jwt_secret": "a" * 40}, "placeholder"),
    ({"database_url": "postgresql+asyncpg://dealhunter:change-me@postgres/dealhunter"}, "database password"),
    ({"database_url": "postgresql+asyncpg://dealhunter@postgres/dealhunter"}, "database password"),
    ({"database_url": "postgresql+asyncpg://u:postgres@postgres/db"}, "database password"),
    ({"cors_origins": "*"}, "https:// origin"),
    ({"cors_origins": "http://localhost:3000"}, "https:// origin"),
    ({"cors_origins": ""}, "CORS_ORIGINS must list"),
    ({"frontend_url": "http://deals.example.com"}, "FRONTEND_URL"),
    ({"use_mock_providers": True}, "sample data"),
    ({"metrics_token": "tooshort"}, "METRICS_TOKEN"),
    ({"smtp_security": "none"}, "SMTP_SECURITY"),
    ({"vapid_public_key": "pub", "vapid_private_key": "priv", "vapid_subject": "admin"}, "VAPID_SUBJECT"),
])
def test_each_unsafe_production_setting_is_reported(over, needle):
    problems = production_problems(prod(**over))
    assert any(needle in p for p in problems), problems


def test_all_problems_are_listed_at_once():
    bad = Settings(app_env="production", jwt_secret="", database_url="postgresql+asyncpg://u:change-me@h/d",
                   cors_origins="http://x", frontend_url="http://x", use_mock_providers=True)
    assert len(production_problems(bad)) >= 5


def test_app_refuses_to_start_in_production_with_unsafe_config(monkeypatch):
    import asyncio

    from app import main

    monkeypatch.setattr(main, "settings", Settings(app_env="production", jwt_secret="", cors_origins="http://x"))

    async def start():
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="Refusing to start"):
        asyncio.run(start())


def test_api_docs_are_not_served_in_production():
    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "c = TestClient(app)\n"
        "print(app.docs_url, app.openapi_url, c.get('/docs').status_code, c.get('/openapi.json').status_code)\n"
    )
    env = {**GOOD_ENV, "APP_ENV": "production"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert out.stdout.strip().endswith("None None 404 404"), out.stdout + out.stderr


GOOD_ENV = {
    "PATH": __import__("os").environ.get("PATH", ""), "PYTHONPATH": __import__("os").pathsep.join(sys.path),
    "JWT_SECRET": GOOD["jwt_secret"], "DATABASE_URL": GOOD["database_url"],
    "CORS_ORIGINS": GOOD["cors_origins"], "FRONTEND_URL": GOOD["frontend_url"],
}


# ------------------------------------------------------------------ URL sanitising
@pytest.mark.parametrize("url", [
    "https://www.amazon.in/dp/B0ABC", "http://example.com/x?a=1&b=2", "HTTPS://Example.com/Path", "https://x.invalid/a%20b",
])
def test_ordinary_http_urls_pass(url):
    assert safe_http_url(url) == url


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)", "file:///etc/passwd", "ftp://example.com/x", "//evil.example/x", "/relative/path", "example.com",
    "http://", "https:///path", "https://user:pass@example.com/", "https://exa mple.com/", "https://example.com/\nSet-Cookie: x=1",
    "https://example.com/\x00", "", None, "https://" + "a" * MAX_URL_LENGTH + ".com",
])
def test_dangerous_or_malformed_urls_are_rejected(url):
    assert safe_http_url(url) is None


def test_require_http_url_raises_with_context():
    with pytest.raises(UnsafeUrlError, match="Product URL"):
        require_http_url("javascript:alert(1)", "Product URL")
    assert require_http_url(" https://ok.example/x ", "Product URL") == "https://ok.example/x"


# ------------------------------------------------------------------ client IP behind proxies
@pytest.mark.parametrize("peer,xff,proxies,expected", [
    ("10.0.0.5", "203.0.113.9", 0, "10.0.0.5"),  # no trusted proxy: header ignored (it is client-controlled)
    ("10.0.0.5", "203.0.113.9", 1, "203.0.113.9"),  # one proxy appended the client address
    ("10.0.0.5", "6.6.6.6, 203.0.113.9", 1, "203.0.113.9"),  # a spoofed leading entry is ignored
    ("10.0.0.5", "203.0.113.9, 10.1.1.1", 2, "203.0.113.9"),
    ("10.0.0.5", "6.6.6.6, 203.0.113.9, 10.1.1.1", 2, "203.0.113.9"),
    ("10.0.0.5", "", 1, "10.0.0.5"),  # header missing: fall back to the peer
    ("10.0.0.5", "203.0.113.9", 3, "10.0.0.5"),  # fewer hops than expected: don't trust it
    (None, None, 0, "unknown"),
])
def test_client_ip(peer, xff, proxies, expected):
    assert client_ip(peer, xff, proxies) == expected


def test_rate_limit_keys_never_contain_email_addresses():
    key = hash_subject("Victim@Example.com")
    assert "victim" not in key.lower() and "@" not in key and key == hash_subject("victim@example.com")


# ------------------------------------------------------------------ request body limit
def _app(limit: int):
    async def echo(request: Request):
        return JSONResponse({"bytes": len(await request.body())})

    return BodySizeLimitMiddleware(Starlette(routes=[Route("/", echo, methods=["POST"])]), max_bytes=limit)


async def _post(limit: int, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(limit)), base_url="http://t") as c:
        return await c.post("/", **kw)


async def test_small_bodies_pass():
    r = await _post(100, content=b"x" * 100)
    assert r.status_code == 200 and r.json() == {"bytes": 100}


async def test_declared_oversize_bodies_get_413_in_the_standard_envelope():
    r = await _post(100, content=b"x" * 101)
    assert r.status_code == 413 and r.json()["success"] is False and r.json()["message"] == "Request body too large"


async def test_streamed_oversize_bodies_get_413_without_a_content_length():
    async def chunks():
        for _ in range(5):
            yield b"x" * 40

    r = await _post(100, content=chunks())  # chunked: no Content-Length to check up front
    assert r.status_code == 413
