"""Products, search, categories, deals and comparison endpoints."""
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.cache import cached
from app.api.deps import ConfigDep, FilterDep, GeneralLimit, PageParam, PageSizeParam, SessionDep, SortParam
from app.schemas.catalog import (
    BuyLink,
    CategoryOut,
    Comparison,
    DealWithEvent,
    OfferOut,
    PriceHistory,
    ProductCard,
    ProductComparison,
    ProductDetail,
)
from app.schemas.common import Envelope, ok, page_meta
from app.services import catalog_query as q
from app.services.deals import recent_events

router = APIRouter(prefix="/api", tags=["catalog"], dependencies=[GeneralLimit])


@router.get("/meta")
async def site_meta():
    """Whether the data is live or demo (mock) data, so the UI never presents samples as real."""
    from app.providers.registry import provider_modes

    providers = [{"name": n, "is_mock": m} for n, m in provider_modes().items()]
    mode = "demo" if any(p["is_mock"] for p in providers) else "live"
    return ok({"data_mode": mode, "providers": providers})


@router.get("/products", response_model=Envelope[list[ProductCard]])
async def list_products(
    session: SessionDep, config: ConfigDep, f: FilterDep,
    sort: SortParam = "newest", page: PageParam = 1, page_size: PageSizeParam = 20,
):
    cards, total = await q.list_products(session, f, sort, page, page_size, config)
    return ok(cards, meta=page_meta(page, page_size, total))


@router.get("/products/{product_id}", response_model=Envelope[ProductDetail])
async def product_detail(product_id: int, session: SessionDep, config: ConfigDep):
    return ok(await q.get_product_detail(session, product_id, config))


@router.get("/products/{product_id}/prices", response_model=Envelope[PriceHistory])
async def product_prices(
    product_id: int, session: SessionDep,
    days: Annotated[int, Query(ge=1, le=730)] = 90, platform: Annotated[str | None, Query(max_length=32)] = None,
):
    history = await q.get_price_history(session, product_id, days, platform)
    return ok(history, message=history.message)


@router.get("/products/{product_id}/offers", response_model=Envelope[list[OfferOut]])
async def product_offers(product_id: int, session: SessionDep):
    return ok(await q.get_offers(session, product_id))


@router.get("/products/{product_id}/compare", response_model=Envelope[Comparison])
async def product_compare(product_id: int, session: SessionDep, config: ConfigDep):
    return ok(await q.compare_product(session, product_id, config))


@router.get("/compare", response_model=Envelope[ProductComparison])
async def compare_many(
    session: SessionDep, config: ConfigDep,
    ids: Annotated[str, Query(description="Comma-separated product ids (2 to 5)", max_length=60)],
):
    parsed = [s.strip() for s in ids.split(",") if s.strip()]
    if not all(s.isdigit() for s in parsed):
        from app.core.errors import ValidationFailed

        raise ValidationFailed("ids must be comma-separated whole numbers")
    return ok(await q.compare_products(session, [int(s) for s in parsed], config))


@router.get("/products/{product_id}/buy", response_model=Envelope[BuyLink])
async def product_buy_link(
    product_id: int, session: SessionDep, platform: Annotated[str | None, Query(max_length=32)] = None
):
    return ok(await q.get_buy_link(session, product_id, platform))


@router.get("/search", response_model=Envelope[list[ProductCard]])
async def search(
    session: SessionDep, config: ConfigDep, f: FilterDep,
    sort: SortParam = "deal_score", page: PageParam = 1, page_size: PageSizeParam = 20,
):
    # The search term arrives as ?q=; a missing/blank term is a client error, not "everything".
    from app.core.errors import ValidationFailed

    if not (f.q and f.q.strip()):
        raise ValidationFailed("Search query 'q' is required")
    cards, total = await q.list_products(session, f, sort, page, page_size, config)
    return ok(cards, meta=page_meta(page, page_size, total))


@router.get("/categories", response_model=Envelope[list[CategoryOut]])
async def categories(request: Request, session: SessionDep):
    async def build():
        return [c.model_dump(mode="json") for c in await q.list_categories(session)]

    return ok(await cached(request, "categories", {}, 300, build))


# ------------------------------------------------------------------------- deals
@router.get("/deals", response_model=Envelope[list[ProductCard]])
async def deals(
    session: SessionDep, config: ConfigDep, f: FilterDep,
    sort: SortParam = "deal_score", page: PageParam = 1, page_size: PageSizeParam = 20,
):
    f.scored_only = True
    cards, total = await q.list_products(session, f, sort, page, page_size, config)
    return ok(cards, meta=page_meta(page, page_size, total))


@router.get("/deals/best", response_model=Envelope[list[ProductCard]])
async def best_deals(
    request: Request, session: SessionDep, config: ConfigDep, f: FilterDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
):
    """Top deals scoring at least a 'good' deal (or the supplied ``deal_score`` minimum)."""
    f.scored_only = True
    f.available_only = True
    f.min_deal_score = f.min_deal_score if f.min_deal_score is not None else config.deal.thresholds.good

    async def build():
        cards, _ = await q.list_products(session, f, "deal_score", 1, limit, config)
        return [c.model_dump(mode="json") for c in cards]

    params = {**{k: str(v) for k, v in f.__dict__.items()}, "limit": limit}
    return ok(await cached(request, "deals_best", params, 60, build))


@router.get("/deals/price-drops", response_model=Envelope[list[DealWithEvent]])
async def price_drops(
    session: SessionDep, config: ConfigDep, f: FilterDep,
    hours: Annotated[int, Query(ge=1, le=720)] = 24, limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return ok(await recent_events(session, "price_drop", f, hours, limit, config))


@router.get("/deals/historical-lows", response_model=Envelope[list[DealWithEvent]])
async def historical_lows(
    session: SessionDep, config: ConfigDep, f: FilterDep,
    hours: Annotated[int, Query(ge=1, le=720)] = 72, limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return ok(await recent_events(session, "historical_low", f, hours, limit, config))
