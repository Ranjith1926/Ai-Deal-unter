"""Administrator endpoints. Every route requires an admin account; every change is audit-logged."""
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import AdminDep, GeneralLimit, SessionDep
from app.providers.registry import provider_modes
from app.schemas.common import Envelope, ok, page_meta
from app.services import admin as svc
from app.services.task_queue import get_queue

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[GeneralLimit])

Page = Annotated[int, Query(ge=1, le=10_000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


# ------------------------------------------------------------------ overview & providers
@router.get("/stats", response_model=Envelope[dict])
async def stats(session: SessionDep, admin: AdminDep):
    return ok(await svc.platform_stats(session, provider_modes()))


class ProviderToggle(BaseModel):
    enabled: bool


@router.put("/providers/{name}", response_model=Envelope[dict])
async def toggle_provider(name: str, body: ProviderToggle, session: SessionDep, admin: AdminDep):
    flags = await svc.set_provider_enabled(session, name, body.enabled)
    svc.log_action(admin, "provider_toggled", provider=name, enabled=body.enabled)
    return ok(flags, message=f"{name.title()} {'enabled' if body.enabled else 'disabled'}")


class JobTrigger(BaseModel):
    job: Literal["sync_catalog", "collect_prices", "recalculate_scores", "update_rankings", "run_pipeline", "process_alerts",
                 "send_notifications"]
    provider: Literal["amazon", "flipkart"] | None = None


@router.post("/jobs/trigger", response_model=Envelope[dict], status_code=202)
async def trigger(body: JobTrigger, admin: AdminDep, queue=Depends(get_queue)):
    task_id = svc.trigger_job(queue, body.job, body.provider)
    svc.log_action(admin, "job_triggered", job=body.job, provider=body.provider, task_id=task_id)
    return ok({"task_id": task_id, "job": body.job, "provider": body.provider}, message="Job queued")


@router.get("/jobs", response_model=Envelope[list[dict]])
async def sync_logs(
    session: SessionDep, admin: AdminDep, provider: str | None = None, status: str | None = None, job: str | None = None,
    failed_only: bool = False, page: Page = 1, page_size: PageSize = 25,
):
    rows, total = await svc.list_sync_logs(session, provider=provider, status=status, job=job, failed_only=failed_only, page=page, page_size=page_size)
    return ok(rows, meta=page_meta(page, page_size, total))


# ------------------------------------------------------------------ categories
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=140)
    parent_id: int | None = Field(default=None, ge=1)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=140)
    parent_id: int | None = Field(default=None, ge=1)


@router.get("/categories", response_model=Envelope[list[dict]])
async def categories(session: SessionDep, admin: AdminDep):
    return ok(await svc.list_categories(session))


@router.post("/categories", response_model=Envelope[dict], status_code=201)
async def add_category(body: CategoryCreate, session: SessionDep, admin: AdminDep):
    created = await svc.create_category(session, body.name, body.slug, body.parent_id)
    svc.log_action(admin, "category_created", category_id=created["id"], slug=created["slug"])
    return ok(created)


@router.patch("/categories/{category_id}", response_model=Envelope[dict])
async def edit_category(category_id: int, body: CategoryUpdate, session: SessionDep, admin: AdminDep):
    sent = body.model_fields_set
    updated = await svc.update_category(session, category_id, body.name, body.slug, body.parent_id, set_parent="parent_id" in sent)
    svc.log_action(admin, "category_updated", category_id=category_id, fields=sorted(sent))
    return ok(updated)


@router.delete("/categories/{category_id}", response_model=Envelope[None])
async def remove_category(category_id: int, session: SessionDep, admin: AdminDep):
    await svc.delete_category(session, category_id)
    svc.log_action(admin, "category_deleted", category_id=category_id)
    return ok(message="Category deleted")


# ------------------------------------------------------------------ products
class ProductUpdate(BaseModel):
    is_active: bool | None = None
    category_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=500)
    brand: str | None = Field(default=None, min_length=1, max_length=120)


class ListingUpdate(BaseModel):
    is_active: bool


@router.get("/products", response_model=Envelope[list[dict]])
async def products(
    session: SessionDep, admin: AdminDep, q: Annotated[str | None, Query(max_length=200)] = None, active: bool | None = None,
    category_id: int | None = None, page: Page = 1, page_size: PageSize = 25,
):
    rows, total = await svc.list_products(session, q=q, active=active, category_id=category_id, page=page, page_size=page_size)
    return ok(rows, meta=page_meta(page, page_size, total))


@router.patch("/products/{product_id}", response_model=Envelope[None])
async def edit_product(product_id: int, body: ProductUpdate, session: SessionDep, admin: AdminDep):
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    await svc.update_product(session, product_id, changes)
    svc.log_action(admin, "product_updated", product_id=product_id, fields=sorted(changes))
    return ok(message="Product updated")


@router.patch("/listings/{listing_id}", response_model=Envelope[None])
async def edit_listing(listing_id: int, body: ListingUpdate, session: SessionDep, admin: AdminDep):
    await svc.set_listing_active(session, listing_id, body.is_active)
    svc.log_action(admin, "listing_toggled", listing_id=listing_id, active=body.is_active)
    return ok(message="Listing updated")


# ------------------------------------------------------------------ scoring configuration
class ScoringOverrides(BaseModel):
    overrides: dict[str, Any]


@router.get("/scoring", response_model=Envelope[dict])
async def scoring(session: SessionDep, admin: AdminDep):
    return ok(await svc.get_scoring(session))


@router.put("/scoring", response_model=Envelope[dict])
async def save_scoring(body: ScoringOverrides, session: SessionDep, admin: AdminDep):
    saved = await svc.set_scoring(session, body.overrides)
    svc.log_action(admin, "scoring_updated", overrides=body.overrides)
    return ok(saved, message="Saved. New scores use these settings the next time they are calculated.")


@router.delete("/scoring", response_model=Envelope[dict])
async def reset_scoring(session: SessionDep, admin: AdminDep):
    reset = await svc.reset_scoring(session)
    svc.log_action(admin, "scoring_reset")
    return ok(reset, message="Reset to the defaults")
