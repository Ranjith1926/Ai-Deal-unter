"""Price collection: normalise, store history (append-only), detect price events."""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.config import ScoringConfig
from app.engine.events import (
    EventSpec,
    Observation,
    detect_price_events,
    should_store_observation,
)
from app.engine.normalize import InvalidPriceError, normalize_price
from app.models import DealEvent, ProductOffer, ProductPlatform, ProductPrice
from app.providers.base import ProviderOffer, ProviderPrice
from app.providers.errors import ProviderError
from app.providers.registry import ProviderHandle
from app.services.common import JobRun, SessionFactory, utcnow

logger = logging.getLogger(__name__)


async def record_events(
    session: AsyncSession,
    product_id: int,
    listing_id: int | None,
    specs: Sequence[EventSpec],
    now: datetime,
    config: ScoringConfig,
) -> int:
    """Persist events, skipping repeats of the same event type inside the cooldown window."""
    cutoff = now - timedelta(hours=config.events.cooldown_hours)
    written = 0
    for spec in specs:
        recent = await session.scalar(
            select(func.count()).select_from(DealEvent).where(
                DealEvent.product_id == product_id,
                DealEvent.event_type == spec.event_type,
                DealEvent.detected_at >= cutoff,
            )
        )
        if recent:
            continue
        session.add(DealEvent(
            product_id=product_id, product_platform_id=listing_id, event_type=spec.event_type,
            price=spec.price, previous_price=spec.previous_price,
            deal_score=None if spec.deal_score is None else Decimal(str(round(spec.deal_score, 2))),
            detail=spec.detail, detected_at=now,
        ))
        written += 1
    return written


async def _latest_observations(session: AsyncSession, listing_ids: Sequence[int]) -> dict[int, Observation]:
    rows = await session.execute(
        select(
            ProductPrice.product_platform_id, ProductPrice.price, ProductPrice.mrp,
            ProductPrice.availability, ProductPrice.seller_name, ProductPrice.captured_at,
        )
        .where(ProductPrice.product_platform_id.in_(listing_ids))
        .ext(distinct_on(ProductPrice.product_platform_id))
        .order_by(ProductPrice.product_platform_id, ProductPrice.captured_at.desc())
    )
    return {r[0]: Observation(r[1], r[3], r[5], r[2], r[4]) for r in rows}


async def _history_summary(
    session: AsyncSession, listing_ids: Sequence[int]
) -> dict[int, tuple[Decimal, int, datetime]]:
    """Per listing: lowest in-stock price, observation count, first observation time."""
    rows = await session.execute(
        select(
            ProductPrice.product_platform_id,
            func.min(ProductPrice.price), func.count(), func.min(ProductPrice.captured_at),
        )
        .where(
            ProductPrice.product_platform_id.in_(listing_ids),
            ProductPrice.availability == "in_stock",
            ProductPrice.price.is_not(None),
        )
        .group_by(ProductPrice.product_platform_id)
    )
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


async def ingest_prices(
    session: AsyncSession,
    listings: Sequence[ProductPlatform],
    prices: Sequence[ProviderPrice],
    config: ScoringConfig,
    run: JobRun,
    now: datetime | None = None,
    detect_events: bool = True,
) -> None:
    """Store new observations for ``listings`` and record resulting price events."""
    now = now or utcnow()
    by_ext = {p.external_id: p for p in prices}
    ids = [l.id for l in listings]
    if not ids:
        return
    latest = await _latest_observations(session, ids)
    summary = await _history_summary(session, ids) if detect_events else {}
    hp = config.history

    rows: list[dict] = []
    pending_events: list[tuple[ProductPlatform, list[EventSpec]]] = []
    for listing in listings:
        pp = by_ext.get(listing.external_product_id)
        if pp is None:
            run.missing += 1
            continue
        run.processed += 1
        try:
            price = normalize_price(pp.price)
            mrp = None
            try:
                mrp = normalize_price(pp.mrp)
            except InvalidPriceError:
                pass  # a bad MRP must not discard a good price
        except InvalidPriceError as exc:
            run.invalid += 1
            logger.warning("Rejected invalid price", extra={"platform": listing.platform, "external_id": listing.external_product_id, "error": str(exc)})
            continue

        availability = pp.availability
        if price is None and availability == "in_stock":
            availability = "unknown"  # contradictory data: claims stock but shows no price

        new = Observation(price, availability, pp.captured_at, mrp, pp.seller_name)
        prev = latest.get(listing.id)
        listing.availability = availability
        listing.last_seen_at = pp.captured_at
        if pp.seller_name:
            listing.seller_name = pp.seller_name
        # Keep the denormalised current price fresh; never let an older observation (e.g. a
        # history backfill) overwrite a newer one.
        if listing.price_captured_at is None or pp.captured_at >= listing.price_captured_at:
            listing.current_price = price if availability == "in_stock" else None
            listing.current_mrp = mrp
            listing.price_captured_at = pp.captured_at
        if not should_store_observation(prev, new, hp):
            continue

        rows.append({
            "product_platform_id": listing.id, "price": price, "mrp": mrp, "currency": pp.currency,
            "availability": availability, "seller_name": pp.seller_name,
            "data_quality": pp.data_quality, "captured_at": pp.captured_at,
        })
        run.stored += 1

        if detect_events:
            low, count, first = summary.get(listing.id, (None, 0, None))
            sufficient = (
                count >= hp.min_observations and first is not None
                and (pp.captured_at - first) >= timedelta(days=hp.min_history_days)
            )
            specs = detect_price_events(prev, new, low, sufficient, config.events)
            if specs:
                pending_events.append((listing, specs))

    if rows:
        await session.execute(insert(ProductPrice), rows)
    for listing, specs in pending_events:
        run.events += await record_events(session, listing.product_id, listing.id, specs, now, config)


def _offer_key(o: ProviderOffer | ProductOffer) -> tuple:
    amount = o.discount_amount
    return (o.offer_type, o.description, None if amount is None else Decimal(amount).quantize(Decimal("0.01")))


async def ingest_offers(
    session: AsyncSession,
    listings: Sequence[ProductPlatform],
    offers: Sequence[ProviderOffer],
    now: datetime | None = None,
) -> None:
    """Keep the offer set per listing current: add new offers, end ones that disappeared."""
    now = now or utcnow()
    ids = [l.id for l in listings]
    if not ids:
        return
    ext_to_id = {l.external_product_id: l.id for l in listings}
    incoming: dict[int, dict[tuple, ProviderOffer]] = {i: {} for i in ids}
    for o in offers:
        lid = ext_to_id.get(o.external_id)
        if lid is not None:
            incoming[lid][_offer_key(o)] = o

    active = await session.scalars(
        select(ProductOffer).where(
            ProductOffer.product_platform_id.in_(ids),
            (ProductOffer.valid_until.is_(None)) | (ProductOffer.valid_until > now),
        )
    )
    current: dict[int, dict[tuple, ProductOffer]] = {i: {} for i in ids}
    for row in active:
        current[row.product_platform_id][_offer_key(row)] = row

    for lid in ids:
        for key, row in current[lid].items():
            if key not in incoming[lid]:
                await session.execute(update(ProductOffer).where(ProductOffer.id == row.id).values(valid_until=now))
        for key, o in incoming[lid].items():
            if key not in current[lid]:
                session.add(ProductOffer(
                    product_platform_id=lid, offer_type=o.offer_type, description=o.description,
                    discount_amount=o.discount_amount, valid_from=o.valid_from,
                    valid_until=o.valid_until, captured_at=now,
                ))


async def collect_prices(
    factory: SessionFactory,
    handle: ProviderHandle,
    config: ScoringConfig,
    run: JobRun,
    batch_size: int = 50,
    now: datetime | None = None,
) -> None:
    """Fetch current prices and offers for every active listing of one provider."""
    provider, guard = handle.provider, handle.guard
    async with factory() as session:
        listing_ids = list(await session.scalars(
            select(ProductPlatform.id).where(
                ProductPlatform.platform == provider.name, ProductPlatform.is_active
            ).order_by(ProductPlatform.id)
        ))

    for start in range(0, len(listing_ids), batch_size):
        chunk = listing_ids[start : start + batch_size]
        try:
            async with factory() as session:
                listings = list(await session.scalars(select(ProductPlatform).where(ProductPlatform.id.in_(chunk))))
                ext_ids = [l.external_product_id for l in listings]
                prices = await guard.call(provider.get_prices, ext_ids)
                offers = await guard.call(provider.get_offers, ext_ids)
                await ingest_prices(session, listings, prices, config, run, now)
                await ingest_offers(session, listings, offers, now)
                await session.commit()
        except ProviderError as exc:
            # One failing batch (or an open circuit) must not abort the whole job.
            run.errors += 1
            run.error = f"{type(exc).__name__}: {exc}"[:2000]
            logger.warning("Price batch failed", extra={"provider": provider.name, "error": str(exc)})
