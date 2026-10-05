"""Event-driven deal views: recent price drops and historical lows."""
from datetime import datetime, timedelta

from sqlalchemy import Float, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.config import ScoringConfig
from app.models import DealEvent
from app.schemas.catalog import DealEventInfo, DealWithEvent
from app.services.catalog_query import ProductFilter, list_products
from app.services.common import utcnow


async def recent_events(
    session: AsyncSession,
    event_type: str,
    f: ProductFilter,
    hours: int = 24,
    limit: int = 20,
    config: ScoringConfig | None = None,
    now: datetime | None = None,
) -> list[DealWithEvent]:
    """Most recent event of ``event_type`` per product within ``hours``, biggest first."""
    now = now or utcnow()
    latest_per_product = (
        select(DealEvent).ext(distinct_on(DealEvent.product_id))
        .where(DealEvent.event_type == event_type, DealEvent.detected_at >= now - timedelta(hours=hours))
        .order_by(DealEvent.product_id, DealEvent.detected_at.desc()).subquery()
    )
    drop = latest_per_product.c.detail["drop_pct"].astext.cast(Float)
    rows = (await session.execute(
        select(
            latest_per_product.c.product_id, latest_per_product.c.event_type, latest_per_product.c.detected_at,
            latest_per_product.c.price, latest_per_product.c.previous_price, latest_per_product.c.detail,
        ).order_by(drop.desc().nulls_last(), latest_per_product.c.detected_at.desc()).limit(500)
    )).all()
    if not rows:
        return []

    ordered_ids = [r.product_id for r in rows]
    # Apply the caller's filters to exactly these products, preserving the event ordering.
    scoped = ProductFilter(**{**f.__dict__, "ids": ordered_ids})
    cards, _ = await list_products(session, scoped, "deal_score", 1, len(ordered_ids), config, now, keep_id_order=True)
    by_id = {c.id: c for c in cards}
    return [
        DealWithEvent(
            product=by_id[r.product_id],
            event=DealEventInfo(
                event_type=r.event_type, detected_at=r.detected_at, price=r.price,
                previous_price=r.previous_price, detail=r.detail or {},
            ),
        )
        for r in rows if r.product_id in by_id
    ][:limit]
