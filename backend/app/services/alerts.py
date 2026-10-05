"""Price-alert processing: find triggered alerts and queue notifications."""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on

from app.core.urls import safe_http_url
from app.engine.config import ScoringConfig
from app.engine.explain import format_inr
from app.models import Notification, PriceAlert, Product, ProductPlatform, ProductPrice, User
from app.services.common import JobRun, SessionFactory, utcnow

logger = logging.getLogger(__name__)

CHANNELS = ("email", "push", "telegram", "in_app")


def channels_for(prefs: dict | None) -> list[str]:
    """External channels the user opted into, plus an in-app copy that is always kept.

    The in-app inbox is the reliable record: an external channel can fail (no push subscription, a blocked bot),
    and the alert must not be lost when it does.
    """
    chosen = [c for c in CHANNELS if c != "in_app" and (prefs or {}).get(c)]
    return chosen + ["in_app"]


async def process_price_alerts(
    factory: SessionFactory, config: ScoringConfig, run: JobRun, now: datetime | None = None
) -> None:
    now = now or utcnow()
    stale_cutoff = now - timedelta(hours=config.history.stale_after_hours)
    async with factory() as session:
        alerts = (await session.execute(
            select(PriceAlert, User, Product.name)
            .join(User, User.id == PriceAlert.user_id)
            .join(Product, Product.id == PriceAlert.product_id)
            .where(PriceAlert.is_active, User.is_active)
        )).all()
        if not alerts:
            return

        product_ids = {a.product_id for a, _, _ in alerts}
        latest = (await session.execute(
            select(
                ProductPlatform.product_id, ProductPlatform.platform, ProductPlatform.url,
                ProductPlatform.affiliate_url, ProductPrice.price, ProductPrice.availability,
                ProductPrice.captured_at,
            )
            .join(ProductPrice, ProductPrice.product_platform_id == ProductPlatform.id)
            .where(ProductPlatform.product_id.in_(product_ids), ProductPlatform.is_active)
            .ext(distinct_on(ProductPlatform.id))
            .order_by(ProductPlatform.id, ProductPrice.captured_at.desc())
        )).all()

        offers: dict[int, list] = {}
        for row in latest:
            # Only fresh, purchasable prices can trigger an alert.
            if row.availability == "in_stock" and row.price is not None and row.captured_at >= stale_cutoff:
                offers.setdefault(row.product_id, []).append(row)

        for alert, user, name in alerts:
            run.processed += 1
            candidates = [
                o for o in offers.get(alert.product_id, [])
                if alert.platform is None or o.platform == alert.platform
            ]
            if not candidates:
                continue
            best = min(candidates, key=lambda o: o.price)
            if best.price > alert.target_price:
                continue

            link = safe_http_url(best.affiliate_url) or safe_http_url(best.url) or ""
            title = f"Price alert: {name}"
            message = (
                f"{name} is now {format_inr(best.price)} on {best.platform.title()} "
                f"(your target: {format_inr(alert.target_price)}). {link}"
            )
            for channel in channels_for(user.notification_preferences):
                session.add(Notification(user_id=user.id, type=channel, title=title, message=message, status="pending"))
            alert.triggered_at = now
            alert.is_active = False  # one-shot: re-arm by creating a new alert
            run.events += 1
        await session.commit()
