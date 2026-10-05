"""Notification dispatch. Channels without credentials are absent, so their messages simply wait."""
import logging
from datetime import datetime, timedelta
from typing import Mapping, Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import ValidationFailed
from app.models import Notification, PushSubscription, User
from app.services.channels import (
    DeliveryError,
    EmailChannel,
    PushChannel,
    TelegramChannel,
    TransientDeliveryError,
    is_allowed_push_endpoint,
)
from app.services.common import JobRun, SessionFactory, utcnow

logger = logging.getLogger(__name__)

SCRUBBED = "[removed after delivery]"


class NotificationChannel(Protocol):
    async def send(self, notification: Notification, user: User) -> None:
        """Deliver one notification. Raise on failure so it is not marked sent."""


class InAppChannel:
    """In-app notifications are delivered by being stored; sending just confirms them."""

    async def send(self, notification: Notification, user: User) -> None:
        return None


def build_channels(settings: Settings | None = None, factory: async_sessionmaker | None = None) -> dict[str, NotificationChannel]:
    """The channels that are configured. Each external channel needs its own credentials."""
    s = settings or get_settings()
    channels: dict[str, NotificationChannel] = {"in_app": InAppChannel()}
    if s.email_enabled:
        channels["email"] = EmailChannel(s)
    if s.telegram_enabled:
        channels["telegram"] = TelegramChannel(s)
    if s.push_enabled and factory is not None:
        channels["push"] = PushChannel(s, factory)
    return channels


def _finish(notification: Notification) -> None:
    """Called when delivery is over (sent or given up): secrets do not outlive it."""
    if notification.is_sensitive:
        notification.message = SCRUBBED


async def expire_stale_sensitive(session: AsyncSession, ttl_minutes: int, now: datetime) -> int:
    """A reset link nobody could deliver (e.g. email not configured) must not sit in the database."""
    result = await session.execute(
        update(Notification)
        .where(Notification.is_sensitive, Notification.status == "pending",
               Notification.created_at < now - timedelta(minutes=ttl_minutes))
        .values(status="failed", message=SCRUBBED, last_error="not delivered in time")
    )
    return result.rowcount or 0


async def dispatch_pending(
    factory: SessionFactory,
    run: JobRun,
    channels: Mapping[str, NotificationChannel] | None = None,
    batch_size: int = 200,
    now: datetime | None = None,
    max_attempts: int | None = None,
    sensitive_ttl_minutes: int | None = None,
) -> None:
    settings = get_settings()
    channels = channels if channels is not None else build_channels(settings, factory)
    max_attempts = max_attempts or settings.notification_max_attempts
    now = now or utcnow()
    async with factory() as session:
        run.extra["expired_sensitive"] = await expire_stale_sensitive(
            session, sensitive_ttl_minutes or settings.sensitive_message_ttl_minutes, now)
        rows = (await session.execute(
            select(Notification, User)
            .join(User, User.id == Notification.user_id)
            .where(Notification.status == "pending", Notification.type.in_(list(channels)))
            .order_by(Notification.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True, of=Notification)
        )).all()
        for notification, user in rows:
            run.processed += 1
            notification.attempts += 1
            try:
                await channels[notification.type].send(notification, user)
            except TransientDeliveryError as exc:
                notification.last_error = str(exc)[:300]
                gave_up = notification.attempts >= max_attempts
                if gave_up:
                    notification.status = "failed"
                    run.errors += 1
                    _finish(notification)
                # Otherwise it stays pending and the next scheduled run tries again.
                logger.warning(
                    "Notification gave up" if gave_up else "Notification delivery will be retried",
                    extra={"notification_id": notification.id, "channel": notification.type, "error": notification.last_error},
                )
            except Exception as exc:  # one bad delivery must not block the rest
                notification.status = "failed"
                # Only our own errors are known to be free of secrets; anything else records just its type.
                notification.last_error = (str(exc) if isinstance(exc, DeliveryError) else type(exc).__name__)[:300]
                run.errors += 1
                _finish(notification)
                logger.warning("Notification failed", extra={
                    "notification_id": notification.id, "channel": notification.type, "error": notification.last_error})
            else:
                notification.status = "sent"
                notification.sent_at = now
                notification.last_error = None
                run.stored += 1
                _finish(notification)
        await session.commit()


# ------------------------------------------------------------------------------------------ user-facing
async def queue_test_notification(session: AsyncSession, user: User, channel: str, settings: Settings | None = None) -> None:
    """Queue a test message on one channel so a user can confirm their setup works."""
    s = settings or get_settings()
    available = {"in_app": True, "email": s.email_enabled, "telegram": s.telegram_enabled, "push": s.push_enabled}
    if channel not in available:
        raise ValidationFailed("Unknown notification channel")
    if not available[channel]:
        raise ValidationFailed(f"{channel.replace('_', ' ').title()} notifications are not available on this server")
    if channel == "telegram" and TelegramChannel.chat_id(user) is None:
        raise ValidationFailed("Save your Telegram chat ID first")
    session.add(Notification(
        user_id=user.id, type=channel, title="Test notification from AI Deal Hunter",
        message="This is a test. If you can read it, price-alert notifications will reach you here.",
    ))
    await session.commit()


async def list_inbox(session: AsyncSession, user_id: int, limit: int = 50) -> list[Notification]:
    return list((await session.scalars(
        select(Notification).where(Notification.user_id == user_id, Notification.type == "in_app")
        .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    )).all())


async def unread_count(session: AsyncSession, user_id: int) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(Notification)
        .where(Notification.user_id == user_id, Notification.type == "in_app", Notification.status != "read")
    ) or 0)


async def mark_read(session: AsyncSession, user_id: int, notification_id: int | None) -> None:
    """Mark one (or, with None, all) in-app notifications as read."""
    stmt = update(Notification).where(
        Notification.user_id == user_id, Notification.type == "in_app", Notification.status != "read")
    if notification_id is not None:
        stmt = stmt.where(Notification.id == notification_id)
    await session.execute(stmt.values(status="read"))
    await session.commit()


# ------------------------------------------------------------------------------------------ web push
MAX_PUSH_SUBSCRIPTIONS = 10  # per account: a handful of browsers/devices


async def save_push_subscription(session: AsyncSession, user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    """Store (or re-assign) a browser's subscription. The endpoint must belong to a known push service."""
    if not get_settings().push_enabled:
        raise ValidationFailed("Push notifications are not available on this server")
    if not is_allowed_push_endpoint(endpoint):
        raise ValidationFailed("This push service is not supported")
    count = await session.scalar(select(func.count()).select_from(PushSubscription).where(
        PushSubscription.user_id == user_id, PushSubscription.endpoint != endpoint))
    if (count or 0) >= MAX_PUSH_SUBSCRIPTIONS:
        # Drop the oldest so a user who reinstalls browsers never gets stuck.
        oldest = await session.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user_id)
                                      .order_by(PushSubscription.created_at).limit(1))
        await session.execute(delete(PushSubscription).where(PushSubscription.id == oldest))
    # One browser = one endpoint. If another account used this browser before, it now belongs to this one.
    stmt = pg_insert(PushSubscription).values(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[PushSubscription.endpoint],
        set_={"user_id": user_id, "p256dh": p256dh, "auth": auth},
    ))
    await session.commit()


async def remove_push_subscription(session: AsyncSession, user_id: int, endpoint: str) -> None:
    await session.execute(delete(PushSubscription).where(
        PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint))
    await session.commit()


async def push_subscription_count(session: AsyncSession, user_id: int) -> int:
    return int(await session.scalar(select(func.count()).select_from(PushSubscription)
                                    .where(PushSubscription.user_id == user_id)) or 0)
