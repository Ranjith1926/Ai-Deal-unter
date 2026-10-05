"""Precomputed deal rankings in Redis, so the API never recomputes history per request."""
import json
import logging
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on

from app.models import Category, Product, ProductScore
from app.services.common import JobRun, SessionFactory, utcnow

logger = logging.getLogger(__name__)

KEY_PREFIX = "dh:"
BEST_DEALS_KEY = f"{KEY_PREFIX}rankings:best_deals"
CATEGORY_KEY = f"{KEY_PREFIX}rankings:category:{{slug}}"
UPDATED_KEY = f"{KEY_PREFIX}rankings:updated_at"
CACHE_PREFIX = f"{KEY_PREFIX}cache:"
RANKING_TTL_SECONDS = 3 * 3600
TOP_N = 200


async def build_ranking_items(factory: SessionFactory) -> list[dict[str, Any]]:
    async with factory() as session:
        latest = (
            select(ProductScore).ext(distinct_on(ProductScore.product_id))
            .order_by(ProductScore.product_id, ProductScore.calculated_at.desc()).subquery()
        )
        rows = (await session.execute(
            select(
                Product.id, Product.name, Product.brand, Product.image_url, Category.slug,
                latest.c.deal_score, latest.c.value_score, latest.c.calculated_at, latest.c.score_reason,
            )
            .join(latest, latest.c.product_id == Product.id)
            .outerjoin(Category, Category.id == Product.category_id)
            .where(Product.is_active, latest.c.deal_score.is_not(None))
            .order_by(latest.c.deal_score.desc(), Product.id)
            .limit(TOP_N)
        )).all()

    items = []
    for pid, name, brand, image, slug, deal, value, calculated, reason in rows:
        best = (reason or {}).get("best_listing", {})
        items.append({
            "product_id": pid, "name": name, "brand": brand, "image_url": image, "category": slug,
            "deal_score": float(deal), "value_score": None if value is None else float(value),
            "label": (reason or {}).get("deal", {}).get("label"),
            "best_platform": best.get("platform"), "best_price": best.get("price"),
            "platform_prices": (reason or {}).get("platform_prices", []),
            "is_stale": (reason or {}).get("deal", {}).get("is_stale", False),
            "calculated_at": calculated.isoformat(),
        })
    return items


async def update_best_deals(factory: SessionFactory, redis_url: str, run: JobRun) -> None:
    items = await build_ranking_items(factory)
    by_category: dict[str, list[dict]] = {}
    for item in items:
        if item["category"]:
            by_category.setdefault(item["category"], []).append(item)

    client = Redis.from_url(redis_url)
    try:
        async with client.pipeline(transaction=True) as pipe:
            pipe.set(BEST_DEALS_KEY, json.dumps(items), ex=RANKING_TTL_SECONDS)
            for slug, group in by_category.items():
                pipe.set(CATEGORY_KEY.format(slug=slug), json.dumps(group), ex=RANKING_TTL_SECONDS)
            pipe.set(UPDATED_KEY, utcnow().isoformat(), ex=RANKING_TTL_SECONDS)
            await pipe.execute()
    finally:
        await client.aclose()
    run.processed, run.stored = len(items), len(items) + len(by_category)


async def cleanup_old_cache(redis_url: str, run: JobRun) -> None:
    """Delete cache keys that were written without an expiry, so they cannot leak forever."""
    client = Redis.from_url(redis_url)
    try:
        async for key in client.scan_iter(match=f"{CACHE_PREFIX}*", count=500):
            run.processed += 1
            if await client.ttl(key) == -1:
                await client.delete(key)
                run.stored += 1
    finally:
        await client.aclose()
