"""Deterministic product recommendations from stored deal and value scores."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.config import ScoringConfig
from app.engine.explain import format_inr
from app.schemas.catalog import ProductCard, Recommendation
from app.services.catalog_query import ProductFilter, list_products

Priority = Literal["balanced", "value", "deal", "price"]
# (value weight, deal weight) for each priority; "price" is handled separately.
_WEIGHTS = {"balanced": (0.5, 0.5), "value": (0.8, 0.2), "deal": (0.2, 0.8)}


class RecommendationRequest(BaseModel):
    category: str | None = Field(default=None, max_length=140)
    brand: str | None = Field(default=None, max_length=120)
    q: str | None = Field(default=None, max_length=200)
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    min_deal_score: float | None = Field(default=None, ge=0, le=100)
    min_value_score: float | None = Field(default=None, ge=0, le=100)
    priority: Priority = "balanced"
    limit: int = Field(default=5, ge=1, le=20)


def _reasons(card: ProductCard) -> list[str]:
    out = []
    if card.deal_score is not None:
        out.append(f"Deal score {card.deal_score:.0f}/100 ({card.deal_label_text})")
    if card.value_score is not None:
        out.append(f"Value score {card.value_score:.0f}/100 against comparable products")
    if card.current_price is not None and card.best_platform:
        out.append(f"Best price {format_inr(card.current_price)} on {card.best_platform.title()}")
    if card.typical_price and card.current_price and card.current_price < card.typical_price:
        out.append(f"{format_inr(card.typical_price - card.current_price)} below its typical price")
    if card.rating:
        out.append(f"Rated {card.rating:.1f}/5" + (f" by {card.review_count:,} buyers" if card.review_count else ""))
    if card.is_stale:
        out.append("Price data may be outdated")
    return out


async def recommend(
    session: AsyncSession,
    req: RecommendationRequest,
    config: ScoringConfig | None = None,
    categories: list[str] | None = None,
) -> list[Recommendation]:
    """Rank in-stock, scored products that fit the request.

    ``categories`` (e.g. a user's favourite categories) is used only when the request does
    not name a category itself.
    """
    base = dict(
        q=req.q, brand=req.brand, min_price=req.min_price, max_price=req.max_price,
        min_deal_score=req.min_deal_score, min_value_score=req.min_value_score, available_only=True,
    )
    if req.category or not categories:
        scopes: list[str | None] = [req.category]
    else:
        scopes = list(categories)

    candidates: dict[int, ProductCard] = {}
    for scope in scopes:
        f = ProductFilter(category=scope, scored_only=req.priority != "price", **base)
        cards, _ = await list_products(session, f, "price_asc" if req.priority == "price" else "deal_score", 1, 50, config)
        candidates.update({c.id: c for c in cards})

    pool = list(candidates.values())
    if req.priority == "price":
        pool.sort(key=lambda c: (c.current_price is None, c.current_price))
        scored = [(100.0 - i, c) for i, c in enumerate(pool)]
    else:
        wv, wd = _WEIGHTS[req.priority]

        def composite(c: ProductCard) -> float:
            parts = [(wv, c.value_score), (wd, c.deal_score)]
            have = [(w, s) for w, s in parts if s is not None]
            total = sum(w for w, _ in have)
            return sum(w * s for w, s in have) / total if total else 0.0  # type: ignore[operator]

        scored = sorted(((composite(c), c) for c in pool), key=lambda t: (-t[0], t[1].id))

    return [
        Recommendation(rank=i, score=round(score, 2), product=card, reasons=_reasons(card))
        for i, (score, card) in enumerate(scored[: req.limit], start=1)
    ]
