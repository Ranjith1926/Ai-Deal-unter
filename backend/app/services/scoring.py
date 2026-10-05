"""Score calculation: deal + value scores per product, stored with their full breakdown."""
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.engine import (
    DealInputs,
    PricePoint,
    PriceStats,
    ProductProfile,
    analyze_discount,
    build_explanation,
    compute_deal_score,
    compute_price_stats,
    compute_value_scores,
    format_inr,
)
from app.engine.config import ScoringConfig
from app.engine.events import detect_score_events, should_store_score
from app.engine.deal_score import DealScore
from app.engine.explain import Reason
from app.models import Category, Product, ProductOffer, ProductPlatform, ProductPrice, ProductScore
from app.services.common import JobRun, SessionFactory, utcnow
from app.services.prices import record_events

logger = logging.getLogger(__name__)

HISTORY_DAYS = 365
PLATFORM_LABELS = {"amazon": "Amazon", "flipkart": "Flipkart"}


@dataclass
class ListingView:
    listing: ProductPlatform
    stats: PriceStats
    points: list[PricePoint]


def _label(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, platform.title())


def _money(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


async def _load_history(
    session: AsyncSession, listing_ids: Sequence[int], since: datetime
) -> dict[int, list[PricePoint]]:
    rows = await session.execute(
        select(
            ProductPrice.product_platform_id, ProductPrice.price, ProductPrice.mrp,
            ProductPrice.availability, ProductPrice.captured_at,
        )
        .where(ProductPrice.product_platform_id.in_(listing_ids), ProductPrice.captured_at >= since)
        .order_by(ProductPrice.product_platform_id, ProductPrice.captured_at)
    )
    out: dict[int, list[PricePoint]] = defaultdict(list)
    for lid, price, mrp, availability, captured in rows:
        out[lid].append(PricePoint(price, captured, availability, mrp))
    return out


async def _active_offer_totals(session: AsyncSession, listing_ids: Sequence[int], now: datetime) -> dict[int, Decimal]:
    rows = await session.scalars(
        select(ProductOffer).where(
            ProductOffer.product_platform_id.in_(listing_ids),
            (ProductOffer.valid_from.is_(None)) | (ProductOffer.valid_from <= now),
            (ProductOffer.valid_until.is_(None)) | (ProductOffer.valid_until > now),
        )
    )
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for o in rows:
        totals[o.product_platform_id] += o.discount_amount or Decimal(0)
    return totals


async def _latest_scores(session: AsyncSession) -> dict[int, Row]:
    """Most recent score per product. Only the columns needed for change detection, not the JSON breakdown."""
    rows = await session.execute(
        select(ProductScore.product_id, ProductScore.deal_score, ProductScore.value_score, ProductScore.calculated_at)
        .ext(distinct_on(ProductScore.product_id))
        .order_by(ProductScore.product_id, ProductScore.calculated_at.desc())
    )
    return {r.product_id: r for r in rows}


def _platform_reasons(views: list[ListingView], best: ListingView) -> list[Reason]:
    live = [v for v in views if v.stats.is_available and not v.stats.current_suspect]
    reasons: list[Reason] = []
    if len(live) >= 2:
        names = " and ".join(sorted(_label(v.listing.platform) for v in live))
        reasons.append(Reason("multi_platform", f"Available on {names}", True))
        others = [v for v in live if v is not best]
        diff = min(v.stats.current_price for v in others) - best.stats.current_price  # type: ignore[operator]
        if diff > 0:
            reasons.append(Reason(
                "cheapest_platform",
                f"{_label(best.listing.platform)} has the lowest price, {format_inr(diff)} cheaper than the next best",
                True,
            ))
    return reasons


def _stats_summary(s: PriceStats) -> dict:
    return {
        "current_price": _money(s.current_price),
        "avg_30d": _money(s.avg(30)), "avg_60d": _money(s.avg(60)), "avg_90d": _money(s.avg(90)),
        "historical_low": _money(s.historical_low), "historical_high": _money(s.historical_high),
        "historical_low_at": None if s.historical_low_at is None else s.historical_low_at.isoformat(),
        "pct_below_30d_avg": s.drop_vs_avg_pct(30), "pct_below_90d_avg": s.drop_vs_avg_pct(90),
        "distance_from_low_pct": s.distance_from_low_pct,
        "previous_price": _money(s.previous_price), "price_drop_pct": s.price_drop_pct, "observation_count": s.observation_count,
        "history_days": round(s.history_days, 1), "is_stale": s.is_stale,
        "captured_at": None if s.current_captured_at is None else s.current_captured_at.isoformat(),
    }


BATCH_PRODUCTS = 250  # products whose price history is held in memory at once


@dataclass
class Computed:
    """Everything a stored score needs, without the (large) price-point lists it was derived from."""

    product_id: int
    category: str | None
    attributes: dict
    price: Decimal | None
    rating: Decimal | None
    review_count: int | None
    best_listing_id: int
    deal: DealScore
    reason: dict  # best_listing, platform_prices, stats, discount, explanation


def _compute_product(
    product: Product, slug: str | None, history: dict[int, list[PricePoint]], offer_totals: dict[int, Decimal],
    config: ScoringConfig, now: datetime,
) -> Computed | None:
    views = []
    for pl in product.platforms:
        if pl.is_active:
            pts = history.get(pl.id, [])
            views.append(ListingView(pl, compute_price_stats(pts, now, config.history), pts))
    if not views:
        return None
    live = [v for v in views if v.stats.is_available and not v.stats.current_suspect]
    best = (
        min(live, key=lambda v: v.stats.current_price)  # type: ignore[arg-type,return-value]
        if live
        else max(views, key=lambda v: v.stats.current_captured_at or datetime.min.replace(tzinfo=now.tzinfo))
    )
    inputs = DealInputs(
        rating=best.listing.rating, review_count=best.listing.review_count, seller_name=best.listing.seller_name,
        offers_total_discount=offer_totals.get(best.listing.id, Decimal(0)),
    )
    deal = compute_deal_score(best.stats, inputs, config)
    mrp = next((p.mrp for p in reversed(best.points) if p.mrp is not None), None)
    discount = analyze_discount(best.stats.current_price, mrp, best.stats, config.discount, config.history)
    reasons = build_explanation(best.stats, deal, discount, inputs, config) + _platform_reasons(views, best)
    reason = {
        "best_listing": {
            "platform": best.listing.platform, "listing_id": best.listing.id, "price": _money(best.stats.current_price),
            "url": best.listing.url, "affiliate_url": best.listing.affiliate_url, "seller": best.listing.seller_name,
        },
        "platform_prices": [
            {"platform": v.listing.platform, "price": _money(v.stats.current_price), "available": v.stats.is_available, "is_stale": v.stats.is_stale}
            for v in views
        ],
        "stats": _stats_summary(best.stats),
        "discount": {
            "advertised_pct": discount.advertised_discount_pct, "typical_price": _money(discount.typical_price),
            "real_saving": _money(discount.real_saving), "real_saving_pct": discount.real_saving_pct,
            "is_misleading": discount.is_misleading,
        },
        "explanation": [{"code": r.code, "text": r.text, "positive": r.positive} for r in reasons],
    }
    return Computed(
        product.id, slug, dict(product.specifications), best.stats.current_price, best.listing.rating,
        best.listing.review_count, best.listing.id, deal, reason,
    )


async def calculate_scores(
    factory: SessionFactory, config: ScoringConfig, run: JobRun, now: datetime | None = None
) -> None:
    now = now or utcnow()
    since = now - timedelta(days=HISTORY_DAYS)
    async with factory() as session:
        products = list((await session.scalars(
            select(Product).where(Product.is_active).options(selectinload(Product.platforms))
        )).unique())
        slugs = dict((await session.execute(select(Category.id, Category.slug))).all())
        previous = await _latest_scores(session)

        # Price history is the bulk of the data, so it is loaded and reduced a batch at a time:
        # memory stays flat as the catalogue and the history grow.
        computed: dict[int, Computed] = {}
        for start in range(0, len(products), BATCH_PRODUCTS):
            batch = products[start : start + BATCH_PRODUCTS]
            listing_ids = [pl.id for p in batch for pl in p.platforms if pl.is_active]
            if not listing_ids:
                continue
            history = await _load_history(session, listing_ids, since)
            offer_totals = await _active_offer_totals(session, listing_ids, now)
            for product in batch:
                c = _compute_product(product, slugs.get(product.category_id), history, offer_totals, config, now)
                if c is not None:
                    computed[product.id] = c
            history = {}  # release this batch's price points before loading the next

        profiles = []
        for c in computed.values():
            hist = c.deal.factor("historical_advantage")
            profiles.append(ProductProfile(
                c.product_id, c.category, c.price, c.attributes, c.rating, c.review_count,
                None if hist is None or c.deal.score is None else hist.score,
            ))
        value_scores = compute_value_scores(profiles, config)

        for product in products:
            c = computed.get(product.id)
            if c is None:
                continue
            run.processed += 1
            value = value_scores.get(product.id)
            deal_score = c.deal.score
            value_score = None if value is None else value.score
            prev = previous.get(product.id)
            prev_deal = None if prev is None or prev.deal_score is None else float(prev.deal_score)
            prev_value = None if prev is None or prev.value_score is None else float(prev.value_score)

            # Products without enough history are normal ("Not enough historical data yet").
            store = should_store_score(prev_deal, prev.calculated_at if prev else None, deal_score, now, config.events) or (
                prev is not None and should_store_score(prev_value, prev.calculated_at, value_score, now, config.events)
            )
            if store:
                session.add(ProductScore(
                    product_id=product.id,
                    deal_score=None if deal_score is None else Decimal(str(deal_score)),
                    value_score=None if value_score is None else Decimal(str(value_score)),
                    calculated_at=now,
                    score_reason={"deal": c.deal.to_reason(), "value": None if value is None else value.to_reason(), **c.reason},
                ))
                run.stored += 1

            specs = detect_score_events(prev_deal, deal_score, c.price, config.events)
            if specs:
                run.events += await record_events(session, product.id, c.best_listing_id, specs, now, config)
        await session.commit()
