"""Shared scoring helpers: clamped linear mapping and the product-quality factor."""
import math
from decimal import Decimal

from app.engine.config import QualityParams


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def linear(x: float, zero_at: float, full_at: float) -> float:
    """Map ``x`` so ``zero_at`` -> 0 and ``full_at`` -> 100, clamped (works in either direction)."""
    if full_at == zero_at:
        return 100.0 if x >= full_at else 0.0
    return clamp((x - zero_at) / (full_at - zero_at) * 100.0)


def quality_score(
    rating: Decimal | float | None, review_count: int | None, params: QualityParams | None = None
) -> float | None:
    """0-100 from rating, scaled by how many reviews back it. ``None`` when no rating exists.

    A 5.0 rating from 3 reviews scores far below a 4.6 from thousands.
    """
    q = params or QualityParams()
    if rating is None:
        return None
    base = linear(float(rating), q.rating_floor, q.rating_ceiling)
    reviews = max(review_count or 0, 0)
    confidence = min(1.0, math.log10(reviews + 1) / math.log10(q.reviews_for_full_confidence + 1))
    return base * confidence
