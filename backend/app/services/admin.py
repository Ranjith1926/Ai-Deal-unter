"""Administration: platform statistics, provider control, job logs, catalogue and scoring settings."""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailed
from app.engine.config import ScoringConfig
from app.models import (
    AppSetting, Category, DealEvent, PriceAlert, Product, ProductPlatform, ProviderSyncLog, User,
)
from app.services.common import utcnow

audit = logging.getLogger("app.audit")

PROVIDERS = ("amazon", "flipkart")
PROVIDERS_KEY = "providers"
SCORING_KEY = "scoring_config"

# Admin-triggerable jobs: public name -> (celery task, needs a provider)
JOBS: dict[str, tuple[str, bool]] = {
    "sync_catalog": ("catalog.sync", True),
    "collect_prices": ("prices.collect_{provider}", True),
    "recalculate_scores": ("scores.calculate", False),
    "update_rankings": ("rankings.update", False),
    "run_pipeline": ("pipeline.run", False),
    "process_alerts": ("alerts.process", False),
    "send_notifications": ("notifications.send", False),
}


class TaskQueue(Protocol):
    def send(self, task: str, args: list[Any]) -> str: ...


def log_action(admin: User, action: str, **details: Any) -> None:
    """Every administrative change leaves a structured audit line."""
    audit.info("admin action", extra={"admin_id": admin.id, "admin_email": admin.email, "action": action, **details})


# ----------------------------------------------------------------------------- providers
async def provider_flags(session: AsyncSession) -> dict[str, bool]:
    row = await session.get(AppSetting, PROVIDERS_KEY)
    stored = (row.value if row else {}) or {}
    return {p: bool((stored.get(p) or {}).get("enabled", True)) for p in PROVIDERS}


async def provider_last_runs(session: AsyncSession, name: str) -> tuple[datetime | None, str | None]:
    """(time of the last successful job, status of the most recent job) for one provider."""
    last_ok = await session.scalar(select(func.max(ProviderSyncLog.completed_at)).where(
        ProviderSyncLog.provider == name, ProviderSyncLog.status == "success"))
    last_status = await session.scalar(select(ProviderSyncLog.status).where(
        ProviderSyncLog.provider == name).order_by(ProviderSyncLog.started_at.desc()).limit(1))
    return last_ok, last_status


async def is_provider_enabled(session: AsyncSession, name: str) -> bool:
    return (await provider_flags(session)).get(name, True)


async def set_provider_enabled(session: AsyncSession, name: str, enabled: bool) -> dict[str, bool]:
    if name not in PROVIDERS:
        raise NotFoundError(f"Unknown provider '{name}'")
    row = await session.get(AppSetting, PROVIDERS_KEY)
    value = dict((row.value if row else {}) or {})
    value[name] = {"enabled": enabled}
    if row is None:
        session.add(AppSetting(key=PROVIDERS_KEY, value=value))
    else:
        row.value = value
    await session.commit()
    return await provider_flags(session)


# ----------------------------------------------------------------------------- statistics
async def platform_stats(session: AsyncSession, provider_modes: dict[str, bool], now: datetime | None = None) -> dict:
    now = now or utcnow()
    day_ago, week_ago = now - timedelta(hours=24), now - timedelta(days=7)

    async def count(stmt) -> int:
        return int(await session.scalar(stmt) or 0)

    products_total = await count(select(func.count(Product.id)))
    products_active = await count(select(func.count(Product.id)).where(Product.is_active))
    listings = dict((await session.execute(
        select(ProductPlatform.platform, func.count()).where(ProductPlatform.is_active).group_by(ProductPlatform.platform))).all())

    events = dict((await session.execute(
        select(DealEvent.event_type, func.count(func.distinct(DealEvent.product_id)))
        .where(DealEvent.detected_at >= day_ago).group_by(DealEvent.event_type))).all())

    users = await count(select(func.count(User.id)))
    alerts_active = await count(select(func.count(PriceAlert.id)).where(PriceAlert.is_active))
    alerts_total = await count(select(func.count(PriceAlert.id)))
    failed_24h = await count(select(func.count(ProviderSyncLog.id)).where(
        ProviderSyncLog.status.in_(("failed", "partial")), ProviderSyncLog.started_at >= day_ago))

    duration = func.extract("epoch", ProviderSyncLog.completed_at - ProviderSyncLog.started_at)
    avg_sync = await session.scalar(select(func.avg(duration)).where(
        ProviderSyncLog.completed_at.is_not(None), ProviderSyncLog.started_at >= week_ago,
        ProviderSyncLog.provider.in_(PROVIDERS)))
    flags = await provider_flags(session)

    providers = []
    for name in PROVIDERS:
        last_ok = await session.scalar(select(func.max(ProviderSyncLog.completed_at)).where(
            ProviderSyncLog.provider == name, ProviderSyncLog.status == "success"))
        last = (await session.execute(
            select(ProviderSyncLog.status, ProviderSyncLog.job_name, ProviderSyncLog.error_message, ProviderSyncLog.started_at)
            .where(ProviderSyncLog.provider == name).order_by(ProviderSyncLog.started_at.desc()).limit(1))).first()
        fails = await count(select(func.count(ProviderSyncLog.id)).where(
            ProviderSyncLog.provider == name, ProviderSyncLog.status.in_(("failed", "partial")), ProviderSyncLog.started_at >= day_ago))
        avg = await session.scalar(select(func.avg(duration)).where(
            ProviderSyncLog.provider == name, ProviderSyncLog.completed_at.is_not(None), ProviderSyncLog.started_at >= week_ago))
        enabled = flags[name]
        fresh = last_ok is not None and now - last_ok <= timedelta(hours=2)
        providers.append({
            "name": name, "enabled": enabled, "mode": "demo" if provider_modes.get(name) else ("live" if name in provider_modes else "unavailable"),
            "listings": int(listings.get(name, 0)),
            "last_success_at": last_ok, "last_status": last[0] if last else None, "last_job": last[1] if last else None,
            "last_error": last[2] if last and last[0] != "success" else None, "failures_24h": fails,
            "avg_sync_seconds": None if avg is None else round(float(avg), 1),
            "health": "disabled" if not enabled else ("healthy" if fresh and (not last or last[0] != "failed") else "attention"),
        })

    return {
        "generated_at": now,
        "products": {"total": products_total, "active": products_active, "amazon": int(listings.get("amazon", 0)), "flipkart": int(listings.get("flipkart", 0))},
        "last_24h": {"deals": int(events.get("new_deal", 0)), "price_drops": int(events.get("price_drop", 0)),
                     "historical_lows": int(events.get("historical_low", 0)), "failed_jobs": failed_24h},
        "users": users, "alerts": {"active": alerts_active, "total": alerts_total},
        "average_sync_seconds": None if avg_sync is None else round(float(avg_sync), 1),
        "last_successful_sync_at": max((p["last_success_at"] for p in providers if p["last_success_at"]), default=None),
        "providers": providers,
    }


async def list_sync_logs(
    session: AsyncSession, *, provider: str | None, status: str | None, job: str | None, failed_only: bool,
    page: int, page_size: int,
) -> tuple[list[dict], int]:
    filters = []
    if provider:
        filters.append(ProviderSyncLog.provider == provider)
    if status:
        filters.append(ProviderSyncLog.status == status)
    if job:
        filters.append(ProviderSyncLog.job_name == job)
    if failed_only:
        filters.append(ProviderSyncLog.status.in_(("failed", "partial")))
    total = int(await session.scalar(select(func.count(ProviderSyncLog.id)).where(*filters)) or 0)
    rows = (await session.scalars(
        select(ProviderSyncLog).where(*filters).order_by(ProviderSyncLog.started_at.desc(), ProviderSyncLog.id.desc())
        .limit(page_size).offset((page - 1) * page_size))).all()
    return [{
        "id": r.id, "provider": r.provider, "job": r.job_name, "status": r.status, "records_processed": r.records_processed,
        "error": r.error_message, "started_at": r.started_at, "completed_at": r.completed_at,
        "duration_seconds": None if r.completed_at is None else round((r.completed_at - r.started_at).total_seconds(), 1),
    } for r in rows], total


def trigger_job(queue: TaskQueue, job: str, provider: str | None) -> str:
    if job not in JOBS:
        raise ValidationFailed(f"Unknown job '{job}'", [f"job must be one of: {', '.join(JOBS)}"])
    task, needs_provider = JOBS[job]
    if needs_provider:
        if provider not in PROVIDERS:
            raise ValidationFailed(f"'{job}' needs a provider", [f"provider must be one of: {', '.join(PROVIDERS)}"])
        return queue.send(task.format(provider=provider), [provider] if job == "sync_catalog" else [])
    return queue.send(task, [])


# ----------------------------------------------------------------------------- categories
def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


async def _category_rows(session: AsyncSession) -> list[dict]:
    counts = dict((await session.execute(select(Product.category_id, func.count()).group_by(Product.category_id))).all())
    cats = (await session.scalars(select(Category).order_by(Category.name))).all()
    return [{"id": c.id, "name": c.name, "slug": c.slug, "parent_id": c.parent_id, "product_count": int(counts.get(c.id, 0))} for c in cats]


async def list_categories(session: AsyncSession) -> list[dict]:
    return await _category_rows(session)


async def create_category(session: AsyncSession, name: str, slug: str | None, parent_id: int | None) -> dict:
    slug = slugify(slug or name)
    if not slug:
        raise ValidationFailed("A category needs a name or slug with letters or numbers")
    if parent_id is not None and await session.get(Category, parent_id) is None:
        raise ValidationFailed("Parent category does not exist")
    category = Category(name=name.strip(), slug=slug, parent_id=parent_id)
    session.add(category)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(f"A category with slug '{slug}' already exists") from None
    return next(c for c in await _category_rows(session) if c["id"] == category.id)


async def update_category(session: AsyncSession, category_id: int, name: str | None, slug: str | None, parent_id: int | None, set_parent: bool) -> dict:
    category = await session.get(Category, category_id)
    if category is None:
        raise NotFoundError("Category not found")
    if name is not None:
        category.name = name.strip()
    if slug is not None:
        category.slug = slugify(slug)
        if not category.slug:
            raise ValidationFailed("Slug must contain letters or numbers")
    if set_parent:
        # Reject cycles: a category cannot sit under itself or its own descendants.
        cursor = parent_id
        while cursor is not None:
            if cursor == category_id:
                raise ValidationFailed("A category cannot be its own ancestor")
            parent = await session.get(Category, cursor)
            if parent is None:
                raise ValidationFailed("Parent category does not exist")
            cursor = parent.parent_id
        category.parent_id = parent_id
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Another category already uses that slug") from None
    return next(c for c in await _category_rows(session) if c["id"] == category_id)


async def delete_category(session: AsyncSession, category_id: int) -> None:
    category = await session.get(Category, category_id)
    if category is None:
        raise NotFoundError("Category not found")
    products = int(await session.scalar(select(func.count(Product.id)).where(Product.category_id == category_id)) or 0)
    children = int(await session.scalar(select(func.count(Category.id)).where(Category.parent_id == category_id)) or 0)
    if products or children:
        raise ConflictError(f"Cannot delete: it still has {products} product(s) and {children} sub-categor{'y' if children == 1 else 'ies'}. Move or remove them first.")
    await session.delete(category)
    await session.commit()


# ----------------------------------------------------------------------------- products
async def list_products(session: AsyncSession, *, q: str | None, active: bool | None, category_id: int | None, page: int, page_size: int) -> tuple[list[dict], int]:
    filters = []
    if q:
        filters.append(Product.name.icontains(q.strip(), autoescape=True) | Product.brand.icontains(q.strip(), autoescape=True))
    if active is not None:
        filters.append(Product.is_active == active)
    if category_id is not None:
        filters.append(Product.category_id == category_id)
    total = int(await session.scalar(select(func.count(Product.id)).where(*filters)) or 0)
    rows = (await session.execute(
        select(Product, Category.name).outerjoin(Category, Category.id == Product.category_id).where(*filters)
        .order_by(Product.id.desc()).limit(page_size).offset((page - 1) * page_size))).all()
    ids = [p.id for p, _ in rows]
    listings: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        for l in await session.scalars(select(ProductPlatform).where(ProductPlatform.product_id.in_(ids)).order_by(ProductPlatform.platform)):
            listings[l.product_id].append({
                "id": l.id, "platform": l.platform, "external_id": l.external_product_id, "is_active": l.is_active,
                "price": l.current_price, "availability": l.availability, "last_seen_at": l.last_seen_at,
                "match_method": l.match_method, "match_confidence": l.match_confidence})
    return [{
        "id": p.id, "name": p.name, "brand": p.brand, "category_id": p.category_id, "category": cat, "is_active": p.is_active,
        "model_number": p.model_number, "created_at": p.created_at, "listings": listings[p.id]} for p, cat in rows], total


async def update_product(session: AsyncSession, product_id: int, changes: dict) -> None:
    product = await session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found")
    if "category_id" in changes and changes["category_id"] is not None and await session.get(Category, changes["category_id"]) is None:
        raise ValidationFailed("Category does not exist")
    for field in ("is_active", "category_id", "name", "brand"):
        if field in changes:
            setattr(product, field, changes[field].strip() if isinstance(changes[field], str) else changes[field])
    await session.commit()


async def set_listing_active(session: AsyncSession, listing_id: int, active: bool) -> None:
    result = await session.execute(update(ProductPlatform).where(ProductPlatform.id == listing_id).values(is_active=active))
    if result.rowcount == 0:
        raise NotFoundError("Listing not found")
    await session.commit()


# ----------------------------------------------------------------------------- scoring configuration
async def get_scoring(session: AsyncSession) -> dict:
    row = await session.get(AppSetting, SCORING_KEY)
    overrides = (row.value if row else {}) or {}
    defaults = ScoringConfig()
    try:
        effective = defaults.with_overrides(overrides)
    except (ValidationError, ValueError):
        effective = defaults  # a stored override that no longer validates is ignored, as the workers do
    return {
        "customised": bool(overrides), "overrides": overrides,
        "defaults": defaults.model_dump(mode="json"), "effective": effective.model_dump(mode="json"),
        "updated_at": row.updated_at if row else None,
    }


async def set_scoring(session: AsyncSession, overrides: dict) -> dict:
    try:
        ScoringConfig().with_overrides(overrides)
    except ValidationError as exc:
        raise ValidationFailed("Invalid scoring settings", [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]) from None
    except (ValueError, TypeError) as exc:
        raise ValidationFailed("Invalid scoring settings", [str(exc)]) from None
    row = await session.get(AppSetting, SCORING_KEY)
    if row is None:
        session.add(AppSetting(key=SCORING_KEY, value=overrides))
    else:
        row.value = overrides
    await session.commit()
    return await get_scoring(session)


async def reset_scoring(session: AsyncSession) -> dict:
    row = await session.get(AppSetting, SCORING_KEY)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return await get_scoring(session)
