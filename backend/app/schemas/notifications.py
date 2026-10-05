"""Notification inbox, channel availability and Web Push subscription payloads."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: int
    title: str
    message: str
    is_read: bool
    created_at: datetime


class InboxOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class ChannelsOut(BaseModel):
    """Which channels this server can deliver on, plus the VAPID key browsers need to subscribe."""

    email: bool
    telegram: bool
    push: bool
    vapid_public_key: str | None
    telegram_bot_username: str | None = None


class TestNotificationIn(BaseModel):
    channel: Literal["in_app", "email", "telegram", "push"]


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=16, max_length=256)
    auth: str = Field(min_length=8, max_length=64)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=1024)
    keys: PushKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=1024)
