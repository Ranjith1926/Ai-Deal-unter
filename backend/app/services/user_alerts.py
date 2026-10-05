"""User-facing price alert management (processing/triggering lives in ``alerts.py``)."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailed
from app.models import PriceAlert, Product, ProductPlatform
from app.schemas.common import Money

MAX_ACTIVE_ALERTS = 50


class AlertCreate(BaseModel):
    product_id: int = Field(gt=0)
    target_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    platform: str | None = Field(default=None, min_length=1, max_length=32)


class AlertOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    target_price: Money
    platform: str | None
    is_active: bool
    triggered_at: datetime | None
    created_at: datetime
    current_price: Money | None = None  # best live price now (on the alert's platform, if set)
    amount_above_target: Money | None = None  # how far the price still has to fall (<= 0 once met)


async def _current_prices(session: AsyncSession, product_ids: list[int]) -> dict[tuple[int, str], Decimal]:
    rows = await session.execute(
        select(ProductPlatform.product_id, ProductPlatform.platform, ProductPlatform.current_price)
        .where(ProductPlatform.product_id.in_(product_ids), ProductPlatform.is_active,
               ProductPlatform.current_price.is_not(None))
    )
    return {(pid, plat): price for pid, plat, price in rows}


def _to_out(alert: PriceAlert, name: str, prices: dict[tuple[int, str], Decimal]) -> AlertOut:
    candidates = [p for (pid, plat), p in prices.items()
                  if pid == alert.product_id and (alert.platform is None or plat == alert.platform)]
    current = min(candidates) if candidates else None
    return AlertOut(
        id=alert.id, product_id=alert.product_id, product_name=name, target_price=alert.target_price,
        platform=alert.platform, is_active=alert.is_active, triggered_at=alert.triggered_at,
        created_at=alert.created_at, current_price=current,
        amount_above_target=None if current is None else current - alert.target_price,
    )


async def create_alert(session: AsyncSession, user_id: int, data: AlertCreate) -> AlertOut:
    product = await session.get(Product, data.product_id)
    if product is None or not product.is_active:
        raise NotFoundError("Product not found")
    platform = data.platform.lower() if data.platform else None
    if platform:
        listed = await session.scalar(select(func.count()).select_from(ProductPlatform).where(
            ProductPlatform.product_id == product.id, ProductPlatform.platform == platform, ProductPlatform.is_active))
        if not listed:
            raise ValidationFailed(f"This product is not listed on {platform}")
    active = await session.scalar(select(func.count()).select_from(PriceAlert).where(
        PriceAlert.user_id == user_id, PriceAlert.is_active))
    if (active or 0) >= MAX_ACTIVE_ALERTS:
        raise ValidationFailed(f"You can have at most {MAX_ACTIVE_ALERTS} active alerts")
    alert = PriceAlert(user_id=user_id, product_id=product.id, target_price=data.target_price, platform=platform)
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return _to_out(alert, product.name, await _current_prices(session, [product.id]))


async def list_alerts(session: AsyncSession, user_id: int, active_only: bool = False) -> list[AlertOut]:
    q = (select(PriceAlert, Product.name).join(Product, Product.id == PriceAlert.product_id)
         .where(PriceAlert.user_id == user_id).order_by(PriceAlert.created_at.desc()))
    if active_only:
        q = q.where(PriceAlert.is_active)
    rows = (await session.execute(q)).all()
    prices = await _current_prices(session, list({a.product_id for a, _ in rows})) if rows else {}
    return [_to_out(a, name, prices) for a, name in rows]


async def delete_alert(session: AsyncSession, user_id: int, alert_id: int) -> None:
    alert = await session.scalar(select(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.user_id == user_id))
    if alert is None:  # also covers other users' alerts: no existence leak
        raise NotFoundError("Alert not found")
    await session.delete(alert)
    await session.commit()
