"""Phase 10: email, Telegram and Web Push delivery, retries, secret scrubbing, inbox and push subscriptions."""
import base64
import json
import os
import threading
import uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import Notification, PushSubscription
from app.services import notifications
from app.services.channels import (
    DeliveryError,
    PushChannel,
    TelegramChannel,
    TransientDeliveryError,
    generate_vapid_keys,
    is_allowed_push_endpoint,
    one_line,
)
from app.services.common import JobRun
from helpers import NOW, add_user, signup

MAILPIT_SMTP = os.getenv("TEST_MAILPIT_HOST", "mailpit")
MAILPIT_API = f"http://{MAILPIT_SMTP}:8025/api/v1"


@pytest.fixture
def settings(monkeypatch):
    """The live settings object, with every external channel switched off unless a test turns it on."""
    s = get_settings()
    for name, value in {"smtp_host": "", "telegram_bot_token": "", "vapid_public_key": "", "vapid_private_key": ""}.items():
        monkeypatch.setattr(s, name, value)
    return s


async def add_note(factory, user_id, kind="email", **kw):
    async with factory() as s:
        note = Notification(user_id=user_id, type=kind, title=kw.pop("title", "t"), message=kw.pop("message", "m"), **kw)
        s.add(note)
        await s.commit()
        return note.id


async def get_note(factory, note_id):
    async with factory() as s:
        return await s.get(Notification, note_id)


# --------------------------------------------------------------------------------------------- helpers
def test_one_line_blocks_header_injection():
    assert one_line("Deal\r\nBcc: victim@example.com") == "Deal Bcc: victim@example.com"
    assert len(one_line("x" * 500)) == 150


@pytest.mark.parametrize("url, ok", [
    ("https://fcm.googleapis.com/fcm/send/abc", True),
    ("https://updates.push.services.mozilla.com/wpush/v2/abc", True),
    ("https://wns2-par02p.notify.windows.com/w/?token=abc", True),
    ("https://web.push.apple.com/QGm", True),
    ("http://fcm.googleapis.com/fcm/send/abc", False),          # not https
    ("https://fcm.googleapis.com.evil.example/x", False),       # suffix trick
    ("https://evilfcm.googleapis.com.example/x", False),
    ("https://169.254.169.254/latest/meta-data", False),        # cloud metadata (SSRF)
    ("https://localhost/x", False),
    ("https://user:pw@fcm.googleapis.com/x", False),
    ("https://fcm.googleapis.com:8443/x", False),
])
def test_push_endpoint_allowlist(url, ok):
    assert is_allowed_push_endpoint(url) is ok


# ------------------------------------------------------------------------------------- dispatch rules
async def test_transient_failures_retry_then_give_up(factory, settings):
    class Flaky:
        async def send(self, notification, user):
            raise TransientDeliveryError("SMTP 451")

    async with factory() as s:
        user = await add_user(s)
        await s.commit()
    nid = await add_note(factory, user.id)
    for attempt in (1, 2):
        await notifications.dispatch_pending(factory, JobRun(), channels={"email": Flaky()}, max_attempts=3)
        note = await get_note(factory, nid)
        assert (note.status, note.attempts, note.last_error) == ("pending", attempt, "SMTP 451")
    run = JobRun()
    await notifications.dispatch_pending(factory, run, channels={"email": Flaky()}, max_attempts=3)
    note = await get_note(factory, nid)
    assert (note.status, note.attempts) == ("failed", 3) and run.errors == 1


async def test_unknown_exceptions_record_only_their_type(factory, settings):
    class Leaky:
        async def send(self, notification, user):
            raise RuntimeError("https://api.example/botSECRET-TOKEN/sendMessage failed")

    async with factory() as s:
        user = await add_user(s)
        await s.commit()
    nid = await add_note(factory, user.id)
    await notifications.dispatch_pending(factory, JobRun(), channels={"email": Leaky()})
    note = await get_note(factory, nid)
    assert note.status == "failed" and note.last_error == "RuntimeError"


async def test_sensitive_message_scrubbed_after_sending(factory, settings):
    sent = []

    class Capture:
        async def send(self, notification, user):
            sent.append(notification.message)

    async with factory() as s:
        user = await add_user(s)
        await s.commit()
    nid = await add_note(factory, user.id, message="reset: https://x/reset-password?token=SECRET", is_sensitive=True)
    await notifications.dispatch_pending(factory, JobRun(), channels={"email": Capture()})
    note = await get_note(factory, nid)
    assert "SECRET" in sent[0]                       # the user got the link...
    assert note.status == "sent" and "SECRET" not in note.message  # ...and the database no longer has it


async def test_undeliverable_sensitive_message_expires(factory, settings):
    async with factory() as s:
        user = await add_user(s)
        await s.commit()
    old = await add_note(factory, user.id, message="token=OLD", is_sensitive=True, created_at=NOW - timedelta(hours=2))
    fresh = await add_note(factory, user.id, message="token=NEW", is_sensitive=True, created_at=NOW)
    run = JobRun()
    # Email is not configured, so nothing can be sent: the old link must still be removed.
    await notifications.dispatch_pending(factory, run, now=NOW, sensitive_ttl_minutes=60)
    old_note, fresh_note = await get_note(factory, old), await get_note(factory, fresh)
    assert (old_note.status, old_note.message) == ("failed", notifications.SCRUBBED)
    assert (fresh_note.status, fresh_note.message) == ("pending", "token=NEW")
    assert run.extra["expired_sensitive"] == 1


async def test_password_reset_notification_is_sensitive(client, factory, settings):
    await signup(client, "reset@example.com")
    assert (await client.post("/api/auth/password-reset/request", json={"email": "reset@example.com"})).status_code in (200, 202)
    async with factory() as s:
        note = await s.scalar(select(Notification).where(Notification.type == "email"))
    assert note.is_sensitive and "reset-password?token=" in note.message


# ----------------------------------------------------------------------------------------------- email
def _mailpit_messages(to: str) -> list[dict]:
    res = httpx.get(f"{MAILPIT_API}/messages", params={"limit": 200}, timeout=5)
    return [m for m in res.json()["messages"] if any(r["Address"] == to for r in m["To"])]


async def test_email_delivered_through_real_smtp(factory, settings, monkeypatch):
    try:
        httpx.get(f"{MAILPIT_API}/messages", timeout=2)
    except httpx.HTTPError:
        pytest.skip("Mailpit not reachable (start the dev stack: docker compose up -d mailpit)")
    monkeypatch.setattr(settings, "smtp_host", MAILPIT_SMTP)
    monkeypatch.setattr(settings, "smtp_port", 1025)
    monkeypatch.setattr(settings, "smtp_security", "none")
    to = f"buyer-{uuid.uuid4().hex[:10]}@example.com"
    async with factory() as s:
        user = await add_user(s, email=to)
        await s.commit()
    nid = await add_note(factory, user.id, title="Price alert: Phone\r\nBcc: attacker@example.com",
                         message="Phone is now ₹23,000 on Flipkart.")
    run = JobRun()
    await notifications.dispatch_pending(factory, run)
    assert (await get_note(factory, nid)).status == "sent" and run.stored == 1

    [msg] = _mailpit_messages(to)
    assert msg["Subject"] == "Price alert: Phone Bcc: attacker@example.com"   # injected header neutralised
    assert msg.get("Bcc") in (None, [])
    full = httpx.get(f"{MAILPIT_API}/message/{msg['ID']}", timeout=5).json()
    assert "₹23,000" in full["Text"] and "notification settings" in full["Text"]


async def test_email_connection_failure_is_retried(factory, settings, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 1)  # nothing listens: a connection problem, so retryable
    async with factory() as s:
        user = await add_user(s)
        await s.commit()
    nid = await add_note(factory, user.id)
    await notifications.dispatch_pending(factory, JobRun())
    note = await get_note(factory, nid)
    assert note.status == "pending" and note.attempts == 1 and "SMTP connection problem" in note.last_error


# -------------------------------------------------------------------------------------------- telegram
def _telegram(settings, handler):
    return TelegramChannel(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_telegram_sends_plain_text_to_saved_chat(factory, settings, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:SECRET")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    async with factory() as s:
        user = await add_user(s, prefs={"telegram": {"chat_id": "42"}})
        await s.commit()
    nid = await add_note(factory, user.id, kind="telegram", title="Price alert: <b>Phone</b>", message="Now ₹23,000")
    await notifications.dispatch_pending(factory, JobRun(), channels={"telegram": _telegram(settings, handler)})
    assert (await get_note(factory, nid)).status == "sent"
    assert seen["url"].endswith("/bot123:SECRET/sendMessage")
    assert seen["body"]["chat_id"] == "42" and "parse_mode" not in seen["body"]
    assert seen["body"]["text"].startswith("Price alert: <b>Phone</b>")


@pytest.mark.parametrize("status, outcome", [(403, "failed"), (400, "failed"), (429, "pending"), (502, "pending")])
async def test_telegram_error_classification(factory, settings, monkeypatch, status, outcome):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:SECRET")
    async with factory() as s:
        user = await add_user(s, prefs={"telegram": {"chat_id": "42"}})
        await s.commit()
    nid = await add_note(factory, user.id, kind="telegram")
    channel = _telegram(settings, lambda r: httpx.Response(status, json={"ok": False}))
    await notifications.dispatch_pending(factory, JobRun(), channels={"telegram": channel})
    note = await get_note(factory, nid)
    assert note.status == outcome and "SECRET" not in (note.last_error or "")


async def test_telegram_network_error_never_leaks_token(factory, settings, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:SECRET")

    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    async with factory() as s:
        user = await add_user(s, prefs={"telegram": {"chat_id": "42"}})
        await s.commit()
    with pytest.raises(TransientDeliveryError) as err:
        await _telegram(settings, handler).send(Notification(title="t", message="m"), user)
    assert "SECRET" not in str(err.value) and err.value.__cause__ is None


async def test_telegram_without_chat_id_fails_permanently(factory, settings):
    async with factory() as s:
        user = await add_user(s, prefs={"telegram": True})
        await s.commit()
    with pytest.raises(DeliveryError):
        await _telegram(settings, lambda r: httpx.Response(200)).send(Notification(title="t", message="m"), user)


# ------------------------------------------------------------------------------------------------ push
class _PushReceiver:
    """A stand-in push service on localhost that records what it receives."""

    def __init__(self, status_for_path: dict[str, int]):
        self.requests: list[dict] = []
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                receiver.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                self.send_response(status_for_path.get(self.path, 201))
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def _browser_keys():
    """What a browser's PushManager.subscribe() produces: an ECDH P-256 key pair and a 16-byte auth secret."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return private, auth, b64(public), b64(auth)


async def test_push_payload_is_encrypted_for_the_browser_and_signed(factory, settings, monkeypatch):
    import http_ece

    public_vapid, private_vapid = generate_vapid_keys()
    monkeypatch.setattr(settings, "vapid_public_key", public_vapid)
    monkeypatch.setattr(settings, "vapid_private_key", private_vapid)
    receiver = _PushReceiver({})
    try:
        browser_private, auth, p256dh, auth_b64 = _browser_keys()
        async with factory() as s:
            user = await add_user(s)
            await s.flush()
            s.add(PushSubscription(user_id=user.id, endpoint=f"{receiver.url}/push/one", p256dh=p256dh, auth=auth_b64))
            await s.commit()
        nid = await add_note(factory, user.id, kind="push", title="Price alert: Phone", message="Now ₹23,000")
        await notifications.dispatch_pending(factory, JobRun(), channels={"push": PushChannel(settings, factory)})
        assert (await get_note(factory, nid)).status == "sent"

        [req] = receiver.requests
        payload = json.loads(http_ece.decrypt(req["body"], private_key=browser_private, auth_secret=auth, version="aes128gcm"))
        assert payload == {"title": "Price alert: Phone", "body": "Now ₹23,000", "url": "/alerts"}
        assert req["headers"]["content-encoding"] == "aes128gcm"
        assert public_vapid in req["headers"]["authorization"]   # VAPID-signed with our key
    finally:
        receiver.close()


async def test_expired_push_subscription_is_removed(factory, settings, monkeypatch):
    public_vapid, private_vapid = generate_vapid_keys()
    monkeypatch.setattr(settings, "vapid_public_key", public_vapid)
    monkeypatch.setattr(settings, "vapid_private_key", private_vapid)
    receiver = _PushReceiver({"/push/gone": 410})
    try:
        async with factory() as s:
            user = await add_user(s)
            await s.flush()
            for path in ("gone", "live"):
                _, _, p256dh, auth = _browser_keys()
                s.add(PushSubscription(user_id=user.id, endpoint=f"{receiver.url}/push/{path}", p256dh=p256dh, auth=auth))
            await s.commit()
        nid = await add_note(factory, user.id, kind="push")
        await notifications.dispatch_pending(factory, JobRun(), channels={"push": PushChannel(settings, factory)})
        assert (await get_note(factory, nid)).status == "sent"  # one browser still got it
        async with factory() as s:
            left = (await s.scalars(select(PushSubscription.endpoint))).all()
        assert left == [f"{receiver.url}/push/live"]
    finally:
        receiver.close()


async def test_push_without_subscription_fails_but_alert_stays_in_inbox(factory, settings):
    async with factory() as s:
        user = await add_user(s)
        await s.commit()
    with pytest.raises(DeliveryError):
        await PushChannel(settings, factory).send(Notification(title="t", message="m"), user)


def test_alerts_always_keep_an_in_app_copy():
    from app.services.alerts import channels_for

    assert channels_for({"push": True}) == ["push", "in_app"]
    assert channels_for({"email": True, "in_app": False}) == ["email", "in_app"]
    assert channels_for(None) == ["in_app"]


# ------------------------------------------------------------------------------------------------- API
async def test_channels_endpoint_reports_availability(client, settings, monkeypatch):
    body = (await client.get("/api/notifications/channels")).json()["data"]
    assert body == {"email": False, "telegram": False, "push": False, "vapid_public_key": None, "telegram_bot_username": None}
    public, private = generate_vapid_keys()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    monkeypatch.setattr(settings, "vapid_private_key", private)
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    body = (await client.get("/api/notifications/channels")).json()["data"]
    assert body["push"] and body["email"] and body["vapid_public_key"] == public


async def test_inbox_lists_and_marks_read_only_own_notifications(client, factory, settings):
    _, mine = await signup(client, "me@example.com")
    _, theirs = await signup(client, "them@example.com")
    async with factory() as s:
        me_id = (await client.get("/api/me", headers=mine)).json()["data"]["id"]
        them_id = (await client.get("/api/me", headers=theirs)).json()["data"]["id"]
        s.add_all([
            Notification(user_id=me_id, type="in_app", title="A", message="a", status="sent"),
            Notification(user_id=me_id, type="email", title="E", message="e"),  # not part of the inbox
            Notification(user_id=them_id, type="in_app", title="B", message="b", status="sent"),
        ])
        await s.commit()
    inbox = (await client.get("/api/me/notifications", headers=mine)).json()["data"]
    assert inbox["unread"] == 1 and [n["title"] for n in inbox["items"]] == ["A"]
    their_id = (await client.get("/api/me/notifications", headers=theirs)).json()["data"]["items"][0]["id"]

    await client.post(f"/api/me/notifications/{their_id}/read", headers=mine)  # someone else's: no effect
    assert (await client.get("/api/me/notifications", headers=theirs)).json()["data"]["unread"] == 1
    await client.post(f"/api/me/notifications/{inbox['items'][0]['id']}/read", headers=mine)
    assert (await client.get("/api/me/notifications", headers=mine)).json()["data"]["unread"] == 0
    assert (await client.get("/api/me/notifications")).status_code == 401


async def test_test_notification(client, factory, settings, monkeypatch):
    _, headers = await signup(client, "tester@example.com")
    r = await client.post("/api/me/notifications/test", headers=headers, json={"channel": "email"})
    assert r.status_code == 422 and "not available" in r.json()["message"]
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    r = await client.post("/api/me/notifications/test", headers=headers, json={"channel": "telegram"})
    assert r.status_code == 422 and "chat ID" in r.json()["message"]
    assert (await client.post("/api/me/notifications/test", headers=headers, json={"channel": "fax"})).status_code == 422
    assert (await client.post("/api/me/notifications/test", headers=headers, json={"channel": "in_app"})).status_code == 202
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Notification).where(Notification.type == "in_app")) == 1


async def test_push_subscription_api(client, factory, settings, monkeypatch):
    _, a = await signup(client, "a@example.com")
    _, b = await signup(client, "b@example.com")
    _, _, p256dh, auth = _browser_keys()
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/device-1", "keys": {"p256dh": p256dh, "auth": auth}}

    r = await client.put("/api/me/push-subscriptions", headers=a, json=sub)
    assert r.status_code == 422 and "not available" in r.json()["message"]  # push not configured yet

    public, private = generate_vapid_keys()
    monkeypatch.setattr(settings, "vapid_public_key", public)
    monkeypatch.setattr(settings, "vapid_private_key", private)
    evil = {**sub, "endpoint": "https://169.254.169.254/latest/meta-data"}
    assert (await client.put("/api/me/push-subscriptions", headers=a, json=evil)).status_code == 422
    assert (await client.put("/api/me/push-subscriptions", headers=a, json=sub)).status_code == 200
    assert (await client.put("/api/me/push-subscriptions", headers=a, json=sub)).status_code == 200  # idempotent
    # The same browser signs in as someone else: the subscription moves with it.
    assert (await client.put("/api/me/push-subscriptions", headers=b, json=sub)).status_code == 200
    async with factory() as s:
        rows = (await s.scalars(select(PushSubscription))).all()
    b_id = (await client.get("/api/me", headers=b)).json()["data"]["id"]
    assert len(rows) == 1 and rows[0].user_id == b_id

    await client.post("/api/me/push-subscriptions/remove", headers=a, json={"endpoint": sub["endpoint"]})  # not a's any more
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(PushSubscription)) == 1
    await client.post("/api/me/push-subscriptions/remove", headers=b, json={"endpoint": sub["endpoint"]})
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(PushSubscription)) == 0
