"""Authenticated user endpoints: profile, notifications, favourites, alerts, recommendations."""
from fastapi import APIRouter, Request, Response, status

from app.api.deps import ConfigDep, GeneralLimit, OptionalUserDep, SessionDep, UserDep, hit_limit
from app.schemas.auth import ProfileUpdate, UserOut
from app.schemas.catalog import CategoryOut, ProductCard, Recommendation
from app.core.config import get_settings
from app.schemas.common import Envelope, ok
from app.schemas.notifications import (
    ChannelsOut,
    InboxOut,
    NotificationOut,
    PushSubscriptionIn,
    PushUnsubscribeIn,
    TestNotificationIn,
)
from app.services import notifications, user_alerts, users
from app.services.recommendations import RecommendationRequest, recommend

router = APIRouter(prefix="/api", tags=["account"], dependencies=[GeneralLimit])


# ------------------------------------------------------------------------- profile
@router.get("/me", response_model=Envelope[UserOut])
async def me(user: UserDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ok(UserOut.model_validate(user))


@router.patch("/me", response_model=Envelope[UserOut])
async def update_me(body: ProfileUpdate, session: SessionDep, user: UserDep):
    user = await users.update_profile(session, user, body.name, body.notification_preferences)
    return ok(UserOut.model_validate(user))


# ------------------------------------------------------------------------- notifications
@router.get("/notifications/channels", response_model=Envelope[ChannelsOut])
async def notification_channels():
    """Which channels this server can deliver on. Public: the profile page needs it before saving."""
    s = get_settings()
    return ok(ChannelsOut(
        email=s.email_enabled, telegram=s.telegram_enabled, push=s.push_enabled,
        vapid_public_key=s.vapid_public_key if s.push_enabled else None,
        telegram_bot_username=s.telegram_bot_username or None,
    ))


@router.get("/me/notifications", response_model=Envelope[InboxOut])
async def inbox(session: SessionDep, user: UserDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    rows = await notifications.list_inbox(session, user.id)
    return ok(InboxOut(
        unread=await notifications.unread_count(session, user.id),
        items=[NotificationOut(id=n.id, title=n.title, message=n.message, is_read=n.status == "read", created_at=n.created_at) for n in rows],
    ))


@router.post("/me/notifications/read", response_model=Envelope[None])
async def mark_all_read(session: SessionDep, user: UserDep):
    await notifications.mark_read(session, user.id, None)
    return ok(message="All marked as read")


@router.post("/me/notifications/{notification_id}/read", response_model=Envelope[None])
async def mark_read(notification_id: int, session: SessionDep, user: UserDep):
    await notifications.mark_read(session, user.id, notification_id)
    return ok(message="Marked as read")


TEST_NOTIFICATIONS_PER_HOUR = 10


@router.post("/me/notifications/test", response_model=Envelope[None], status_code=status.HTTP_202_ACCEPTED)
async def send_test(body: TestNotificationIn, request: Request, session: SessionDep, user: UserDep):
    # Each test reaches a real inbox or phone (and costs SMTP quota), so it has its own per-account limit.
    await hit_limit(request, "notify-test", str(user.id), TEST_NOTIFICATIONS_PER_HOUR, 3600)
    await notifications.queue_test_notification(session, user, body.channel)
    return ok(message="Test queued. It should arrive within a few minutes.")


@router.put("/me/push-subscriptions", response_model=Envelope[None])
async def subscribe_push(body: PushSubscriptionIn, session: SessionDep, user: UserDep):
    await notifications.save_push_subscription(session, user.id, body.endpoint, body.keys.p256dh, body.keys.auth)
    return ok(message="Push notifications are on for this browser")


@router.post("/me/push-subscriptions/remove", response_model=Envelope[None])
async def unsubscribe_push(body: PushUnsubscribeIn, session: SessionDep, user: UserDep):
    await notifications.remove_push_subscription(session, user.id, body.endpoint)
    return ok(message="Push notifications are off for this browser")


# ------------------------------------------------------------------------- favourites
@router.get("/me/favorites/products", response_model=Envelope[list[ProductCard]])
async def favorite_products(session: SessionDep, user: UserDep, config: ConfigDep):
    return ok(await users.list_favorite_products(session, user.id, config))


@router.put("/me/favorites/products/{product_id}", response_model=Envelope[None])
async def add_favorite_product(product_id: int, session: SessionDep, user: UserDep):
    await users.add_favorite_product(session, user.id, product_id)
    return ok(message="Saved to favourites")


@router.delete("/me/favorites/products/{product_id}", response_model=Envelope[None])
async def remove_favorite_product(product_id: int, session: SessionDep, user: UserDep):
    await users.remove_favorite_product(session, user.id, product_id)
    return ok(message="Removed from favourites")


@router.get("/me/favorites/categories", response_model=Envelope[list[CategoryOut]])
async def favorite_categories(session: SessionDep, user: UserDep):
    return ok(await users.list_favorite_categories(session, user.id))


@router.put("/me/favorites/categories/{slug}", response_model=Envelope[None])
async def add_favorite_category(slug: str, session: SessionDep, user: UserDep):
    await users.add_favorite_category(session, user.id, slug)
    return ok(message="Category saved")


@router.delete("/me/favorites/categories/{slug}", response_model=Envelope[None])
async def remove_favorite_category(slug: str, session: SessionDep, user: UserDep):
    await users.remove_favorite_category(session, user.id, slug)
    return ok(message="Category removed")


# ------------------------------------------------------------------------- alerts
@router.post("/alerts", response_model=Envelope[user_alerts.AlertOut], status_code=status.HTTP_201_CREATED)
async def create_alert(body: user_alerts.AlertCreate, session: SessionDep, user: UserDep):
    return ok(await user_alerts.create_alert(session, user.id, body), "Alert created")


@router.get("/alerts", response_model=Envelope[list[user_alerts.AlertOut]])
async def list_alerts(session: SessionDep, user: UserDep, active_only: bool = False):
    return ok(await user_alerts.list_alerts(session, user.id, active_only))


@router.delete("/alerts/{alert_id}", response_model=Envelope[None])
async def delete_alert(alert_id: int, session: SessionDep, user: UserDep):
    await user_alerts.delete_alert(session, user.id, alert_id)
    return ok(message="Alert deleted")


# ------------------------------------------------------------------------- recommendations
@router.get("/recommendations", response_model=Envelope[list[Recommendation]])
async def recommendations(session: SessionDep, config: ConfigDep, user: OptionalUserDep, limit: int = 8):
    """Top picks. Signed-in users with favourite categories get picks from those categories."""
    favourites = await users.favorite_category_slugs(session, user.id) if user else None
    req = RecommendationRequest(limit=max(1, min(limit, 20)))
    return ok(await recommend(session, req, config, favourites))


@router.post("/recommendations", response_model=Envelope[list[Recommendation]])
async def recommendations_for(body: RecommendationRequest, session: SessionDep, config: ConfigDep):
    return ok(await recommend(session, body, config))
