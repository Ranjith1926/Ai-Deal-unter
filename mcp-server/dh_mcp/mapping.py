"""Convert REST API payloads into the compact MCP output models (presentation only)."""
from typing import Any

from dh_mcp.models import (
    AdvertisedVsReal,
    AlertInfo,
    OfferInfo,
    ProductSummary,
    ScoreFactor,
    StoreComparison,
    StorePrice,
    clean,
)

FACTOR_NAMES = {
    "historical_advantage": "price vs typical price", "recent_drop": "recent price drop",
    "distance_from_low": "closeness to lowest price", "product_quality": "ratings and reviews",
    "seller_reliability": "seller reliability", "available_offers": "extra offers",
    "price_stability": "price stability", "spec_value": "performance per rupee",
    "quality": "ratings and reviews", "historical_pricing": "price vs its own history",
}


def store_price(p: dict) -> StorePrice:
    return StorePrice(
        store=p["platform"], price=p.get("price"), mrp=p.get("mrp"), available=p.get("price") is not None,
        seller=clean(p.get("seller"), 80), price_may_be_outdated=bool(p.get("is_stale")),
    )


def summary(c: dict) -> ProductSummary:
    return ProductSummary(
        id=c["id"], name=clean(c["name"], 200) or "", brand=clean(c["brand"], 80) or "", category=c.get("category"),
        price=c.get("current_price"), best_store=c.get("best_platform"),
        store_prices=[store_price(p) for p in c.get("platforms", [])],
        typical_price=c.get("typical_price"), historical_low=c.get("historical_low"),
        price_drop_pct=c.get("price_drop_pct"), advertised_discount_pct=c.get("advertised_discount_pct"),
        deal_score=c.get("deal_score"), value_score=c.get("value_score"),
        deal_rating=c.get("deal_label_text", "Not enough history yet"),
        rating=c.get("rating"), review_count=c.get("review_count"),
        price_updated_at=c.get("price_updated_at"), price_may_be_outdated=bool(c.get("is_stale")),
        note=clean(c.get("note"), 160),
    )


def advertised_vs_real(d: dict | None) -> AdvertisedVsReal | None:
    if not d:
        return None
    return AdvertisedVsReal(
        advertised_discount_pct=d.get("advertised_pct"), typical_price=d.get("typical_price"),
        real_saving=d.get("real_saving"), real_saving_pct=d.get("real_saving_pct"),
        advertised_discount_is_misleading=d.get("is_misleading"),
    )


def reasons_and_cautions(explanation: list[dict]) -> tuple[list[str], list[str]]:
    return (
        [clean(e["text"], 200) or "" for e in explanation if e.get("positive")],
        [clean(e["text"], 200) or "" for e in explanation if not e.get("positive")],
    )


def offers(items: list[dict]) -> list[OfferInfo]:
    return [
        OfferInfo(store=o["platform"], type=o["offer_type"], description=clean(o["description"], 160) or "",
                  discount_amount=o.get("discount_amount"))
        for o in items
    ]


def factors(breakdown: dict | None) -> list[ScoreFactor]:
    return [
        ScoreFactor(factor=FACTOR_NAMES.get(f["key"], f["key"]), weight_pct=round(f["weight"] * 100, 1), score=f.get("score"))
        for f in (breakdown or {}).get("factors", [])
    ]


def store_comparison(p: dict) -> StoreComparison:
    return StoreComparison(
        store=p["platform"], price=p.get("price"), mrp=p.get("mrp"),
        difference_vs_cheapest=p.get("difference_vs_cheapest"), seller=clean(p.get("seller"), 80),
        bank_offers=[clean(o["description"], 160) or "" for o in p.get("bank_offers", [])],
        exchange_offers=[clean(o["description"], 160) or "" for o in p.get("exchange_offers", [])],
        estimated_price_after_offers=p.get("price_after_offers"), price_may_be_outdated=bool(p.get("is_stale")),
    )


def alert(a: dict) -> AlertInfo:
    status = "reached" if a.get("triggered_at") else ("watching" if a.get("is_active") else "inactive")
    return AlertInfo(
        id=a["id"], product_id=a["product_id"], product_name=clean(a["product_name"], 200) or "",
        target_price=a["target_price"], store=a.get("platform"), status=status, current_price=a.get("current_price"),
        amount_above_target=a.get("amount_above_target"), created_at=a["created_at"], triggered_at=a.get("triggered_at"),
    )


def sample(points: list[dict], limit: int) -> tuple[list[dict], bool]:
    """Evenly thin a series to at most ``limit`` points, always keeping the first and last."""
    if len(points) <= limit:
        return points, False
    step = (len(points) - 1) / (limit - 1)
    idx = sorted({round(i * step) for i in range(limit)})
    return [points[i] for i in idx], True


def num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None
