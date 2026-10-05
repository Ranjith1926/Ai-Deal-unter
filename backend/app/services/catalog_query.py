"""Read-side queries: product lists/search, detail, price history, comparison and buy links.

Everything here reads precomputed data (denormalised current prices and stored scores), so no
historical-price calculation happens per request.
"""
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import Float, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailed
from app.core.urls import safe_http_url
from app.engine.config import ScoringConfig
from app.engine.deal_score import LABEL_DISPLAY
from app.engine.explain import format_inr
from app.engine.normalize import normalize_title
from app.models import Category, Product, ProductOffer, ProductPlatform, ProductPrice, ProductScore
from app.schemas.catalog import (
    BuyLink,
    CategoryOut,
    Comparison,
    DiscountInfo,
    ExplanationItem,
    OfferOut,
    PlatformComparison,
    PlatformPrice,
    PriceHistory,
    PricePointOut,
    ProductCard,
    ProductComparison,
    ProductDetail,
)
from app.services.common import utcnow

SORTS = ("deal_score", "value_score", "price_asc", "price_desc", "newest", "name", "price_drop")
INSUFFICIENT = "Not enough historical data yet"

# Everyday words people (and AI assistants) use for the category slugs.
CATEGORY_ALIASES = {
    "phone": "mobiles", "phones": "mobiles", "mobile": "mobiles", "smartphone": "mobiles", "smartphones": "mobiles",
    "laptop": "laptops", "notebook": "laptops", "notebooks": "laptops",
    "television": "tv", "televisions": "tv", "tvs": "tv", "smart tv": "tv",
    "headphone": "electronics", "headphones": "electronics", "earbuds": "electronics", "earphones": "electronics",
    "appliance": "home-appliances", "appliances": "home-appliances", "home appliance": "home-appliances",
    "washing machine": "home-appliances", "home-appliance": "home-appliances",
}


async def resolve_category(session: AsyncSession, text: str) -> str:
    """Map "laptop", "Laptops", "phones"... to a real category slug; unknown text is returned as typed."""
    wanted = " ".join(text.lower().replace("_", " ").split())
    rows = (await session.execute(select(Category.slug, Category.name))).all()
    slugs = {slug for slug, _ in rows}
    names = {name.lower(): slug for slug, name in rows}
    for candidate in (wanted.replace(" ", "-"), wanted, wanted + "s", wanted.rstrip("s"), CATEGORY_ALIASES.get(wanted, "")):
        if candidate in slugs:
            return candidate
        if candidate in names:
            return names[candidate]
    return wanted.replace(" ", "-")


@dataclass
class ProductFilter:
    q: str | None = None
    category: str | None = None
    brand: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    platform: str | None = None
    min_deal_score: float | None = None
    min_value_score: float | None = None
    scored_only: bool = False  # only products that have a deal score
    available_only: bool = False  # only products with a live price
    ids: Sequence[int] | None = None


@dataclass
class _Score:
    deal_score: float | None
    value_score: float | None
    calculated_at: datetime | None
    reason: dict


def _dec(value: Any) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


# --------------------------------------------------------------------------- query building
def _latest_scores():
    return (
        select(ProductScore).ext(distinct_on(ProductScore.product_id))
        .order_by(ProductScore.product_id, ProductScore.calculated_at.desc()).subquery("latest")
    )


def _live_prices(platform: str | None):
    q = select(
        ProductPlatform.product_id, func.min(ProductPlatform.current_price).label("best_price")
    ).where(ProductPlatform.is_active, ProductPlatform.current_price.is_not(None))
    if platform:
        q = q.where(ProductPlatform.platform == platform.lower())
    return q.group_by(ProductPlatform.product_id).subquery("live")


def _apply_filters(stmt, f: ProductFilter, latest, live):
    stmt = stmt.where(Product.is_active)
    if f.ids is not None:
        stmt = stmt.where(Product.id.in_(list(f.ids)))
    if f.q:
        for token in normalize_title(f.q).split():
            stmt = stmt.where(
                Product.normalized_name.icontains(token, autoescape=True)
                | Product.brand.icontains(token, autoescape=True)
                | Product.model_number.icontains(token, autoescape=True)
            )
    if f.category:
        stmt = stmt.where(Category.slug == f.category.lower())
    if f.brand:
        stmt = stmt.where(func.lower(Product.brand) == f.brand.strip().lower())
    if f.platform or f.available_only or f.min_price is not None or f.max_price is not None:
        stmt = stmt.where(live.c.best_price.is_not(None))
    if f.min_price is not None:
        stmt = stmt.where(live.c.best_price >= f.min_price)
    if f.max_price is not None:
        stmt = stmt.where(live.c.best_price <= f.max_price)
    if f.scored_only or f.min_deal_score is not None:
        stmt = stmt.where(latest.c.deal_score.is_not(None))
    if f.min_deal_score is not None:
        stmt = stmt.where(latest.c.deal_score >= f.min_deal_score)
    if f.min_value_score is not None:
        stmt = stmt.where(latest.c.value_score >= f.min_value_score)
    return stmt


def _order(sort: str, latest, live):
    drop = latest.c.score_reason["stats"]["price_drop_pct"].astext.cast(Float)
    mapping = {
        "deal_score": [latest.c.deal_score.desc().nulls_last()],
        "value_score": [latest.c.value_score.desc().nulls_last()],
        "price_asc": [live.c.best_price.asc().nulls_last()],
        "price_desc": [live.c.best_price.desc().nulls_last()],
        "newest": [Product.created_at.desc()],
        "name": [func.lower(Product.name).asc()],
        "price_drop": [drop.desc().nulls_last()],
    }
    return [*mapping[sort], Product.id]


# --------------------------------------------------------------------------- card building
def build_card(
    product: Product,
    category: str | None,
    listings: Sequence[ProductPlatform],
    score: _Score | None,
    now: datetime,
    stale_after: timedelta,
) -> ProductCard:
    reason = score.reason if score else {}
    stats = reason.get("stats", {}) or {}
    deal = reason.get("deal", {}) or {}
    discount = reason.get("discount", {}) or {}

    def stale(ts: datetime | None) -> bool:
        return ts is None or (now - ts) > stale_after

    # Links are re-checked on the way out as well (defence in depth for rows written before validation existed).
    def link(l: ProductPlatform) -> str | None:
        return safe_http_url(l.affiliate_url) or safe_http_url(l.url)

    platforms = [
        PlatformPrice(
            platform=l.platform, price=l.current_price, mrp=l.current_mrp, availability=l.availability,
            seller=l.seller_name, buy_url=link(l), is_affiliate_link=bool(safe_http_url(l.affiliate_url)),
            updated_at=l.price_captured_at, is_stale=stale(l.price_captured_at),
            rating=_f(l.rating), review_count=l.review_count,
        )
        for l in sorted(listings, key=lambda x: (x.current_price is None, x.current_price or 0, x.platform))
    ]
    live = [l for l in listings if l.current_price is not None]
    best = min(live, key=lambda l: (l.current_price, l.platform)) if live else None
    newest = max((l.price_captured_at for l in listings if l.price_captured_at), default=None)
    updated = best.price_captured_at if best else newest

    label = deal.get("label") or "insufficient_data"
    deal_score = score.deal_score if score else None
    note = None
    if deal_score is None:
        note = deal.get("insufficient_reason") or INSUFFICIENT

    return ProductCard(
        id=product.id, name=product.name, brand=product.brand, category=category, image_url=safe_http_url(product.image_url),
        current_price=best.current_price if best else None,
        previous_price=_dec(stats.get("previous_price")),
        typical_price=_dec(discount.get("typical_price")) or _dec(stats.get("avg_90d")) or _dec(stats.get("avg_30d")),
        historical_low=_dec(stats.get("historical_low")),
        price_drop_pct=stats.get("price_drop_pct"),
        advertised_discount_pct=discount.get("advertised_pct"),
        deal_score=deal_score, value_score=score.value_score if score else None,
        deal_label=label, deal_label_text=LABEL_DISPLAY.get(label, LABEL_DISPLAY["insufficient_data"]),
        note=note, score_calculated_at=score.calculated_at if score else None,
        best_platform=best.platform if best else None, platforms=platforms,
        rating=_f(best.rating) if best else None, review_count=best.review_count if best else None,
        buy_url=link(best) if best else None,
        is_affiliate_link=bool(best and safe_http_url(best.affiliate_url)),
        price_updated_at=updated, is_stale=stale(updated),
    )


async def _listings_by_product(session: AsyncSession, ids: Sequence[int]) -> dict[int, list[ProductPlatform]]:
    out: dict[int, list[ProductPlatform]] = defaultdict(list)
    if ids:
        rows = await session.scalars(
            select(ProductPlatform).where(ProductPlatform.product_id.in_(list(ids)), ProductPlatform.is_active)
        )
        for l in rows:
            out[l.product_id].append(l)
    return out


# --------------------------------------------------------------------------- public queries
async def list_products(
    session: AsyncSession,
    f: ProductFilter,
    sort: str = "deal_score",
    page: int = 1,
    page_size: int = 20,
    config: ScoringConfig | None = None,
    now: datetime | None = None,
    keep_id_order: bool = False,
) -> tuple[list[ProductCard], int]:
    if sort not in SORTS:
        raise ValidationFailed(f"Unknown sort '{sort}'", [f"sort must be one of: {', '.join(SORTS)}"])
    if f.min_price is not None and f.max_price is not None and f.min_price > f.max_price:
        raise ValidationFailed("min_price must not exceed max_price")
    cfg = config or ScoringConfig()
    now = now or utcnow()
    if f.category:
        f = replace(f, category=await resolve_category(session, f.category))
    latest, live = _latest_scores(), _live_prices(f.platform)

    joins = lambda s: (  # noqa: E731
        s.select_from(Product)
        .outerjoin(Category, Category.id == Product.category_id)
        .outerjoin(latest, latest.c.product_id == Product.id)
        .outerjoin(live, live.c.product_id == Product.id)
    )
    total = await session.scalar(_apply_filters(joins(select(func.count(Product.id))), f, latest, live)) or 0

    stmt = joins(select(
        Product, Category.slug, latest.c.deal_score, latest.c.value_score,
        latest.c.calculated_at, latest.c.score_reason,
    ))
    stmt = _apply_filters(stmt, f, latest, live).order_by(*_order(sort, latest, live))
    if not keep_id_order:
        stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    rows = (await session.execute(stmt)).all()

    listings = await _listings_by_product(session, [r[0].id for r in rows])
    stale_after = timedelta(hours=cfg.history.stale_after_hours)
    cards = [
        build_card(
            p, slug, listings.get(p.id, []),
            _Score(_f(deal), _f(value), calculated, reason or {}) if calculated else None,
            now, stale_after,
        )
        for p, slug, deal, value, calculated, reason in rows
    ]
    if keep_id_order and f.ids is not None:
        position = {pid: i for i, pid in enumerate(f.ids)}
        cards.sort(key=lambda c: position.get(c.id, 1 << 30))
    return cards, total


async def _active_offers(session: AsyncSession, listings: Sequence[ProductPlatform], now: datetime) -> list[OfferOut]:
    platform_of = {l.id: l.platform for l in listings}
    if not platform_of:
        return []
    rows = await session.scalars(
        select(ProductOffer).where(
            ProductOffer.product_platform_id.in_(list(platform_of)),
            (ProductOffer.valid_from.is_(None)) | (ProductOffer.valid_from <= now),
            (ProductOffer.valid_until.is_(None)) | (ProductOffer.valid_until > now),
        ).order_by(ProductOffer.product_platform_id, ProductOffer.id)
    )
    return [
        OfferOut(
            platform=platform_of[o.product_platform_id], offer_type=o.offer_type, description=o.description,
            discount_amount=o.discount_amount, valid_until=o.valid_until,
        )
        for o in rows
    ]


async def _load_product(session: AsyncSession, product_id: int) -> tuple[Product, str | None]:
    row = (await session.execute(
        select(Product, Category.slug).outerjoin(Category, Category.id == Product.category_id)
        .where(Product.id == product_id, Product.is_active)
    )).first()
    if row is None:
        raise NotFoundError("Product not found")
    return row[0], row[1]


async def _latest_score(session: AsyncSession, product_id: int) -> _Score | None:
    s = await session.scalar(
        select(ProductScore).where(ProductScore.product_id == product_id)
        .order_by(ProductScore.calculated_at.desc()).limit(1)
    )
    return None if s is None else _Score(_f(s.deal_score), _f(s.value_score), s.calculated_at, s.score_reason or {})


async def get_product_detail(
    session: AsyncSession, product_id: int, config: ScoringConfig | None = None, now: datetime | None = None
) -> ProductDetail:
    cfg, now = config or ScoringConfig(), now or utcnow()
    product, slug = await _load_product(session, product_id)
    listings = (await _listings_by_product(session, [product_id])).get(product_id, [])
    score = await _latest_score(session, product_id)
    card = build_card(product, slug, listings, score, now, timedelta(hours=cfg.history.stale_after_hours))
    reason = score.reason if score else {}
    d = reason.get("discount")
    return ProductDetail(
        **card.model_dump(),
        description=product.description, model_number=product.model_number, variant_key=product.variant_key,
        specifications=dict(product.specifications or {}),
        explanation=[ExplanationItem(**e) for e in reason.get("explanation", [])],
        discount=None if not d else DiscountInfo(
            advertised_pct=d.get("advertised_pct"), typical_price=_dec(d.get("typical_price")),
            real_saving=_dec(d.get("real_saving")), real_saving_pct=d.get("real_saving_pct"),
            is_misleading=d.get("is_misleading"),
        ),
        offers=await _active_offers(session, listings, now),
        stats=reason.get("stats"), score_breakdown={"deal": reason.get("deal"), "value": reason.get("value")} if reason else None,
    )


async def get_offers(session: AsyncSession, product_id: int, now: datetime | None = None) -> list[OfferOut]:
    await _load_product(session, product_id)
    listings = (await _listings_by_product(session, [product_id])).get(product_id, [])
    return await _active_offers(session, listings, now or utcnow())


async def get_price_history(
    session: AsyncSession, product_id: int, days: int = 90, platform: str | None = None, now: datetime | None = None
) -> PriceHistory:
    if not 1 <= days <= 730:
        raise ValidationFailed("days must be between 1 and 730")
    now = now or utcnow()
    await _load_product(session, product_id)
    listings = [
        l for l in (await _listings_by_product(session, [product_id])).get(product_id, [])
        if platform is None or l.platform == platform.lower()
    ]
    daily = days > 14
    series: dict[str, list[PricePointOut]] = {}
    for listing in listings:
        rows = (await session.execute(
            select(ProductPrice.captured_at, ProductPrice.price, ProductPrice.availability)
            .where(ProductPrice.product_platform_id == listing.id, ProductPrice.captured_at >= now - timedelta(days=days))
            .order_by(ProductPrice.captured_at)
        )).all()
        points: list[PricePointOut] = []
        if not daily:
            points = [PricePointOut(t=t, price=p if a == "in_stock" else None, available=a == "in_stock") for t, p, a in rows]
        else:
            buckets: dict[Any, list] = defaultdict(list)
            for t, p, a in rows:
                buckets[t.date()].append((t, p, a))
            for day, items in sorted(buckets.items()):
                live = [(t, p) for t, p, a in items if a == "in_stock" and p is not None]
                points.append(PricePointOut(
                    t=items[-1][0], price=live[-1][1] if live else None,
                    low=min(p for _, p in live) if live else None, high=max(p for _, p in live) if live else None,
                    available=bool(live),
                ))
        series[listing.platform] = points

    score = await _latest_score(session, product_id)
    reason = score.reason if score else {}
    deal = reason.get("deal", {}) or {}
    insufficient = score is None or deal.get("insufficient_reason") == INSUFFICIENT
    return PriceHistory(
        product_id=product_id, days=days, resolution="daily" if daily else "raw", series=series,
        stats=reason.get("stats"), has_sufficient_history=not insufficient,
        message=INSUFFICIENT if insufficient else None,
    )


async def compare_product(
    session: AsyncSession, product_id: int, config: ScoringConfig | None = None, now: datetime | None = None
) -> Comparison:
    cfg, now = config or ScoringConfig(), now or utcnow()
    product, _ = await _load_product(session, product_id)
    listings = (await _listings_by_product(session, [product_id])).get(product_id, [])
    offers = await _active_offers(session, listings, now)
    stale_after = timedelta(hours=cfg.history.stale_after_hours)

    live = [l for l in listings if l.current_price is not None]
    cheapest = min(live, key=lambda l: (l.current_price, l.platform)) if live else None
    rows: list[PlatformComparison] = []
    for l in sorted(listings, key=lambda x: (x.current_price is None, x.current_price or 0, x.platform)):
        mine = [o for o in offers if o.platform == l.platform]
        total = sum((o.discount_amount or Decimal(0) for o in mine), Decimal(0))
        rows.append(PlatformComparison(
            platform=l.platform, price=l.current_price, mrp=l.current_mrp, availability=l.availability,
            seller=l.seller_name,
            bank_offers=[o for o in mine if o.offer_type == "bank"],
            exchange_offers=[o for o in mine if o.offer_type == "exchange"],
            other_offers=[o for o in mine if o.offer_type not in ("bank", "exchange")],
            price_after_offers=(max(l.current_price - total, Decimal(0)) if l.current_price is not None and mine else None),
            difference_vs_cheapest=(l.current_price - cheapest.current_price) if cheapest and l.current_price is not None else None,
            buy_url=safe_http_url(l.affiliate_url) or safe_http_url(l.url), is_affiliate_link=bool(safe_http_url(l.affiliate_url)),
            updated_at=l.price_captured_at,
            is_stale=l.price_captured_at is None or (now - l.price_captured_at) > stale_after,
        ))

    spread = None
    if len(live) >= 2:
        spread = max(l.current_price for l in live) - cheapest.current_price  # type: ignore[union-attr]
    if cheapest is None:
        summary = "Currently unavailable on all tracked platforms."
    elif len(live) == 1:
        summary = f"Only available on {cheapest.platform.title()} at {format_inr(cheapest.current_price)}."
    else:
        next_best = min((l for l in live if l is not cheapest), key=lambda l: l.current_price)
        diff = next_best.current_price - cheapest.current_price
        summary = (
            f"{cheapest.platform.title()} is cheapest at {format_inr(cheapest.current_price)}"
            + (f", {format_inr(diff)} less than {next_best.platform.title()} ({format_inr(next_best.current_price)})."
               if diff > 0 else f", the same price as {next_best.platform.title()}.")
        )
    return Comparison(
        product_id=product_id, product_name=product.name, platforms=rows,
        best_platform=cheapest.platform if cheapest else None, price_difference=spread, summary=summary,
    )


def _best(products: list[ProductDetail], value, pick_max: bool) -> ProductDetail | None:
    scored = [(value(p), p) for p in products if value(p) is not None]
    if len(scored) < 2:  # a "winner" among one candidate is meaningless
        return None
    return (max if pick_max else min)(scored, key=lambda t: (t[0], -t[1].id if pick_max else t[1].id))[1]


async def compare_products(
    session: AsyncSession, ids: Sequence[int], config: ScoringConfig | None = None, now: datetime | None = None
) -> ProductComparison:
    """Side-by-side comparison of 2-5 products with a plain-language verdict."""
    unique = list(dict.fromkeys(ids))
    if not 2 <= len(unique) <= 5:
        raise ValidationFailed("Provide between 2 and 5 distinct product ids to compare")
    products = [await get_product_detail(session, pid, config, now) for pid in unique]

    cheapest = _best(products, lambda p: p.current_price, pick_max=False)
    top_value = _best(products, lambda p: p.value_score, pick_max=True)
    top_deal = _best(products, lambda p: p.deal_score, pick_max=True)
    lines: list[str] = []
    if cheapest:
        lines.append(f"{cheapest.name} has the lowest price ({format_inr(cheapest.current_price)}).")
    if top_value:
        extra = ", even though it isn't the cheapest, because it offers more for the money" if cheapest and top_value.id != cheapest.id else ""
        lines.append(f"{top_value.name} has the best value score ({top_value.value_score:.0f}/100){extra}.")
    if top_deal:
        lines.append(f"{top_deal.name} is the best deal right now relative to its own price history ({top_deal.deal_score:.0f}/100).")
    if not lines:
        lines.append("Not enough data to pick a clear winner yet.")
    return ProductComparison(
        products=products,
        spec_keys=sorted({k for p in products for k in p.specifications}),
        cheapest_id=cheapest.id if cheapest else None,
        best_value_id=top_value.id if top_value else None,
        best_deal_id=top_deal.id if top_deal else None,
        summary=lines,
    )


async def get_buy_link(session: AsyncSession, product_id: int, platform: str | None = None) -> BuyLink:
    """The affiliate link when the listing has one, else the plain product URL. Never constructed."""
    await _load_product(session, product_id)
    listings = (await _listings_by_product(session, [product_id])).get(product_id, [])
    if platform:
        match = [l for l in listings if l.platform == platform.lower()]
        if not match:
            raise NotFoundError(f"Product is not listed on {platform}")
        chosen = match[0]
    else:
        live = [l for l in listings if l.current_price is not None]
        if not live and not listings:
            raise NotFoundError("Product has no marketplace listings")
        chosen = min(live, key=lambda l: (l.current_price, l.platform)) if live else listings[0]
    affiliate = bool(safe_http_url(chosen.affiliate_url))
    url = safe_http_url(chosen.affiliate_url) or safe_http_url(chosen.url)
    if url is None:
        raise NotFoundError("No valid link is available for this listing")
    return BuyLink(
        product_id=product_id, platform=chosen.platform, url=url,
        is_affiliate_link=affiliate,
        note=None if affiliate else "Direct product link; no affiliate tracking is configured for this listing.",
    )


async def list_categories(session: AsyncSession) -> list[CategoryOut]:
    rows = (await session.execute(
        select(Category.id, Category.name, Category.slug, func.count(Product.id))
        .outerjoin(Product, (Product.category_id == Category.id) & Product.is_active)
        .group_by(Category.id).order_by(Category.name)
    )).all()
    return [CategoryOut(id=i, name=n, slug=s, product_count=c) for i, n, s, c in rows]
