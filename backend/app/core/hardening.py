"""Production safety checks and request-level protections."""
import hashlib
import json
from urllib.parse import urlsplit

from app.core.config import Settings

_WEAK_SECRET_FRAGMENTS = ("change", "secret", "password", "example", "test", "default", "xxxx", "1234")


def production_problems(s: Settings) -> list[str]:
    """Everything that must be fixed before the API may start with APP_ENV=production."""
    if not s.is_production:
        return []
    problems: list[str] = []

    secret = s.jwt_secret
    if len(secret) < 32:
        problems.append("JWT_SECRET must be at least 32 characters (generate one with `openssl rand -hex 32`)")
    elif any(f in secret.lower() for f in _WEAK_SECRET_FRAGMENTS) or len(set(secret)) < 8:
        problems.append("JWT_SECRET looks like a placeholder; use a long random value")

    db = urlsplit(s.database_url.replace("+asyncpg", ""))
    if not db.password or "change-me" in (db.password or "") or db.password in ("password", "postgres"):
        problems.append("DATABASE_URL uses a default or empty database password")

    origins = s.cors_origin_list
    if not origins:
        problems.append("CORS_ORIGINS must list the site origin(s)")
    for origin in origins:
        if origin == "*" or not origin.startswith("https://"):
            problems.append(f"CORS_ORIGINS entry {origin!r} must be an https:// origin (no wildcards)")
    if not s.frontend_url.startswith("https://"):
        problems.append("FRONTEND_URL must be an https:// URL (it is used in password-reset links)")

    if s.use_mock_providers:
        problems.append("USE_MOCK_PROVIDERS=true: sample data must never be served in production")
    if s.smtp_host and s.smtp_security not in ("starttls", "ssl"):
        problems.append("SMTP_SECURITY must be starttls or ssl in production (mail would carry reset links in clear text)")
    if s.push_enabled and not s.vapid_subject.startswith(("mailto:", "https://")):
        problems.append("VAPID_SUBJECT must be a mailto: or https:// contact")
    if s.metrics_token and len(s.metrics_token) < 24:
        problems.append("METRICS_TOKEN must be at least 24 characters")
    return problems


def client_ip(peer: str | None, forwarded_for: str | None, trusted_proxies: int) -> str:
    """The real client address.

    With ``trusted_proxies`` reverse proxies in front, each appends its peer to X-Forwarded-For, so the
    client is the Nth entry from the right. Entries further left are client-supplied and ignored.
    """
    peer = peer or "unknown"
    if trusted_proxies <= 0 or not forwarded_for:
        return peer
    parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
    return parts[-trusted_proxies] if len(parts) >= trusted_proxies else peer


def hash_subject(value: str) -> str:
    """Stable, non-reversible key part, so rate-limit keys never contain email addresses."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:24]


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Reject oversized request bodies (declared or streamed) with 413 before the app buffers them."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return await self._reject(send)

        received, started, rejected = 0, False, False

        async def limited_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Answer right now: the framework would otherwise turn our exception into a 500.
                    if not started and not rejected:
                        rejected = True
                        await self._reject(send)
                    raise _TooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if rejected:  # we already replied 413; drop whatever the app tries to send afterwards
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            pass

    async def _reject(self, send):
        body = json.dumps({"success": False, "data": None, "message": "Request body too large", "errors": []}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
