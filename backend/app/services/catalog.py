"""Catalogue sync: discover marketplace products, normalise, match and upsert."""
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.urls import UnsafeUrlError, require_http_url, safe_http_url
from app.engine.config import ScoringConfig
from app.engine.matching import MatchResult, ProductIdentity, match_candidate
from app.engine.normalize import build_variant_key, normalize_brand, normalize_title
from app.models import Category, Product, ProductPlatform
from app.providers.base import ProviderProduct
from app.providers.registry import ProviderHandle
from app.services.common import JobRun, SessionFactory, utcnow

logger = logging.getLogger(__name__)


@dataclass
class UpsertOutcome:
    product_id: int
    listing_id: int
    created_product: bool
    created_listing: bool
    match: MatchResult | None


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _clean_gtin(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits if 8 <= len(digits) <= 14 else None


def _clean_rating(value: Decimal | None) -> Decimal | None:
    try:
        return value if value is not None and Decimal(0) <= value <= Decimal(5) else None
    except InvalidOperation:
        return None


async def _category_id(session: AsyncSession, slug: str | None) -> int | None:
    if not slug:
        return None
    slug = slugify(slug)
    existing = await session.scalar(select(Category.id).where(Category.slug == slug))
    if existing:
        return existing
    category = Category(name=slug.replace("-", " ").title(), slug=slug)
    session.add(category)
    await session.flush()
    return category.id


def _identity(p: Product) -> ProductIdentity:
    return ProductIdentity(
        brand=normalize_brand(p.brand),
        model_number=p.model_number,
        gtin=p.gtin,
        asin=p.asin,
        variant_key=p.variant_key,
        normalized_title=p.normalized_name,
        product_id=p.id,
    )


async def upsert_listing(
    session: AsyncSession,
    platform: str,
    pp: ProviderProduct,
    config: ScoringConfig,
    now: datetime | None = None,
) -> UpsertOutcome:
    """Insert or update one marketplace listing, matching it to a canonical product."""
    now = now or utcnow()
    rating = _clean_rating(pp.rating)
    # Provider data is untrusted: a `javascript:` URL here would become script execution when rendered as a link.
    url = require_http_url(pp.url, "Product URL")
    image_url = safe_http_url(pp.image_url)

    listing = await session.scalar(
        select(ProductPlatform).where(
            ProductPlatform.platform == platform, ProductPlatform.external_product_id == pp.external_id
        )
    )
    if listing is not None:
        listing.url = url
        listing.seller_name = pp.seller_name or listing.seller_name
        listing.rating, listing.review_count = rating, pp.review_count
        listing.last_seen_at, listing.is_active = now, True
        return UpsertOutcome(listing.product_id, listing.id, False, False, None)

    brand = normalize_brand(pp.brand)
    title = normalize_title(pp.title)
    variant_key = build_variant_key(pp.variant_attributes)
    model = (pp.model_number or "").strip().upper() or None
    gtin = _clean_gtin(pp.gtin)
    asin = (pp.asin or "").strip().upper() or None

    conditions = [and_(func.lower(Product.brand) == brand, Product.normalized_name == title)]
    if gtin:
        conditions.append(Product.gtin == gtin)
    if asin:
        conditions.append(Product.asin == asin)
    if model:
        conditions.append(and_(func.lower(Product.brand) == brand, Product.model_number == model))
    rows = (await session.scalars(select(Product).where(or_(*conditions)))).all()

    candidate = ProductIdentity(brand, model, gtin, asin, variant_key, title)
    match = match_candidate(candidate, [_identity(p) for p in rows], config.matching)

    created_product = False
    if match.product_id is not None:
        product = next(p for p in rows if p.id == match.product_id)
        # Fill identifiers the product lacks, unless another product already owns them.
        if product.gtin is None and gtin and not any(r.gtin == gtin for r in rows):
            product.gtin = gtin
        if product.asin is None and asin and not any(r.asin == asin for r in rows):
            product.asin = asin
        if product.model_number is None and model:
            product.model_number = model
        if not product.image_url and image_url:
            product.image_url = image_url
        confidence, method = Decimal(str(match.confidence)), match.method
    else:
        if match.confidence:
            logger.info(
                "Listing not merged: %s (confidence %.0f)", match.reason, match.confidence,
                extra={"platform": platform, "external_id": pp.external_id},
            )
        # Never reuse an identifier another product owns (unique indexes), e.g. a refused merge.
        if gtin and any(r.gtin == gtin for r in rows):
            gtin = None
        if asin and any(r.asin == asin for r in rows):
            asin = None
        product = Product(
            brand=(pp.brand or "Unknown").strip(),
            name=pp.title[:500],
            normalized_name=title[:500],
            category_id=await _category_id(session, pp.category),
            model_number=model,
            gtin=gtin,
            asin=asin,
            variant_key=variant_key,
            specifications={k.lower(): v for k, v in {**pp.specifications, **pp.variant_attributes}.items()},
            image_url=image_url,
        )
        session.add(product)
        await session.flush()
        created_product = True
        confidence, method = Decimal("100"), "created"

    listing = ProductPlatform(
        product_id=product.id,
        platform=platform,
        external_product_id=pp.external_id,
        url=url,
        seller_name=pp.seller_name,
        availability="unknown",
        match_confidence=confidence,
        match_method=method,
        rating=rating,
        review_count=pp.review_count,
        last_seen_at=now,
    )
    session.add(listing)
    await session.flush()
    return UpsertOutcome(product.id, listing.id, created_product, True, match)


async def sync_catalog(
    factory: SessionFactory,
    handle: ProviderHandle,
    config: ScoringConfig,
    run: JobRun,
    category: str | None = None,
    page_size: int = 50,
) -> None:
    """Page through a provider's products and upsert each listing."""
    provider, guard = handle.provider, handle.guard
    cursor: str | None = None
    while True:
        page = await guard.call(provider.list_products, category, cursor, page_size)
        async with factory() as session:
            for pp in page.items:
                run.processed += 1
                try:
                    async with session.begin_nested():
                        outcome = await upsert_listing(session, provider.name, pp, config)
                        if outcome.created_listing:
                            run.stored += 1
                            if not provider.is_mock:  # mocks never have links; skip the API call
                                link = safe_http_url(await guard.call(provider.get_buy_link, pp.external_id))
                                if link:  # only ever a valid link the provider/affiliate API returned
                                    listing = await session.get(ProductPlatform, outcome.listing_id)
                                    listing.affiliate_url = link  # type: ignore[union-attr]
                except IntegrityError as exc:
                    run.errors += 1
                    logger.warning("Could not upsert listing", extra={"external_id": pp.external_id, "error": str(exc.orig)})
                except UnsafeUrlError as exc:
                    run.errors += 1
                    logger.warning("Rejected listing with unsafe URL", extra={"external_id": pp.external_id, "error": str(exc)})
            await session.commit()
        cursor = page.next_cursor
        if not cursor:
            return
