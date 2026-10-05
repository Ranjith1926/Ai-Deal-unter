"""Delivery channels: email (SMTP), Telegram (Bot API) and Web Push (VAPID).

Each channel raises ``TransientDeliveryError`` for problems worth retrying (timeouts, 5xx, rate limits) and any
other exception for permanent ones (bad address, blocked bot, expired subscription). Secrets never appear in
error text: Telegram's token lives in the request URL, so httpx exceptions are replaced with a short message.
"""
import asyncio
import json
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.models import Notification, PushSubscription, User

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 15
TELEGRAM_TIMEOUT_SECONDS = 10
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")

# Push endpoints are chosen by the client, and this server POSTs to them, so only the push services of the
# major browsers are accepted (a free-form URL would let a user aim the server at internal addresses).
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)


class DeliveryError(Exception):
    """Permanent failure: do not retry."""


class TransientDeliveryError(DeliveryError):
    """Temporary failure: retry on a later run."""


def one_line(text: str, limit: int = 150) -> str:
    """Collapse control characters (header-injection defence) and cap the length."""
    return _CONTROL.sub(" ", text).strip()[:limit]


def is_allowed_push_endpoint(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and not parts.username and not parts.password
        and parts.port in (None, 443)
        and len(endpoint) <= 1024
        and any(host == s or host.endswith("." + s) for s in PUSH_HOST_SUFFIXES)
    )


# ------------------------------------------------------------------------------------------------ email
class EmailChannel:
    def __init__(self, settings: Settings):
        self.s = settings

    def _build(self, notification: Notification, user: User) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.s.email_from
        msg["To"] = formataddr((one_line(user.name, 80), user.email))
        msg["Subject"] = one_line(notification.title, 150)
        body = notification.message
        if not notification.is_sensitive:
            body += "\n\n--\nYou receive this because of your AI Deal Hunter notification settings (Profile > Notifications)."
        msg.set_content(body)
        return msg

    def _send_sync(self, msg: EmailMessage) -> None:
        s = self.s
        try:
            if s.smtp_security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_SECONDS, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT_SECONDS)
            with server:
                if s.smtp_security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password)
                server.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            raise DeliveryError("recipient address refused") from exc
        except smtplib.SMTPResponseException as exc:
            # 4xx = try again later; 5xx = rejected for good.
            cls = TransientDeliveryError if 400 <= exc.smtp_code < 500 else DeliveryError
            raise cls(f"SMTP {exc.smtp_code}") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise TransientDeliveryError(f"SMTP connection problem ({type(exc).__name__})") from exc

    async def send(self, notification: Notification, user: User) -> None:
        await asyncio.to_thread(self._send_sync, self._build(notification, user))


# ---------------------------------------------------------------------------------------------- telegram
class TelegramChannel:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client

    @staticmethod
    def chat_id(user: User) -> str | None:
        tg = (user.notification_preferences or {}).get("telegram")
        return str(tg["chat_id"]) if isinstance(tg, dict) and tg.get("chat_id") else None

    async def send(self, notification: Notification, user: User) -> None:
        chat_id = self.chat_id(user)
        if chat_id is None:
            raise DeliveryError("no Telegram chat ID saved")
        url = f"{self.s.telegram_api_base.rstrip('/')}/bot{self.s.telegram_bot_token}/sendMessage"
        # No parse_mode: marketplace titles are plain text and must not be interpreted as markup.
        payload = {"chat_id": chat_id, "text": f"{one_line(notification.title, 200)}\n\n{notification.message}"[:4000],
                   "disable_web_page_preview": True}
        try:
            if self._client is not None:
                res = await self._client.post(url, json=payload, timeout=TELEGRAM_TIMEOUT_SECONDS)
            else:
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, json=payload, timeout=TELEGRAM_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:  # message would include the URL, and so the bot token
            raise TransientDeliveryError(f"Telegram unreachable ({type(exc).__name__})") from None
        if res.status_code == 200:
            return
        if res.status_code == 429 or res.status_code >= 500:
            raise TransientDeliveryError(f"Telegram HTTP {res.status_code}")
        raise DeliveryError(f"Telegram rejected the message (HTTP {res.status_code})")  # blocked bot, bad chat id, ...


# ------------------------------------------------------------------------------------------------- push
class PushChannel:
    def __init__(self, settings: Settings, factory: async_sessionmaker):
        self.s = settings
        self.factory = factory

    def _push_sync(self, sub: PushSubscription, payload: str) -> int | None:
        """Returns None on success, or the HTTP status of a failed push."""
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload, vapid_private_key=self.s.vapid_private_key,
                vapid_claims={"sub": self.s.vapid_subject}, ttl=86400, timeout=10,
            )
            return None
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status is None:
                raise TransientDeliveryError("push service unreachable") from None
            return status
        except (OSError, httpx.HTTPError):
            raise TransientDeliveryError("push service unreachable") from None

    async def send(self, notification: Notification, user: User) -> None:
        async with self.factory() as session:
            subs = list((await session.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id))).all())
        if not subs:
            raise DeliveryError("no push subscription on this account")
        payload = json.dumps({"title": one_line(notification.title, 100), "body": notification.message[:300], "url": "/alerts"})
        delivered, gone, transient = 0, [], 0
        for sub in subs:
            status = await asyncio.to_thread(self._push_sync, sub, payload)
            if status is None:
                delivered += 1
            elif status in (404, 410):
                gone.append(sub.id)  # the browser unsubscribed; stop sending to it
            elif status == 429 or status >= 500:
                transient += 1
        if gone:
            async with self.factory() as session:
                await session.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
                await session.commit()
        if delivered:
            return
        if transient:
            raise TransientDeliveryError("push service busy")
        raise DeliveryError("every push subscription was rejected or expired")


def generate_vapid_keys() -> tuple[str, str]:
    """(public, private) as base64url strings, the formats browsers and pywebpush expect."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    raw_private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    raw_public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return b64(raw_public), b64(raw_private)
