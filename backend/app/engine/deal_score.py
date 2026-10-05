"""Transparent 0-100 Deal Score.

The score is built only from stored price history plus quality/seller/offer signals. The
seller's advertised discount (MRP) is deliberately **not** an input, so a big claimed discount
cannot create a high score on its own.

If history is insufficient the score is ``None`` with a reason; nothing is invented.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.engine.config import DealParams, QualityParams, ScoringConfig
from app.engine.history import PriceStats
from app.engine.quality import linear, quality_score

Label = Literal["exceptional", "great", "good", "average", "poor", "insufficient_data"]

LABEL_DISPLAY: dict[str, str] = {
    "exceptional": "🔥 Exceptional Deal",
    "great": "🟢 Great Deal",
    "good": "🟡 Good Deal",
    "average": "🟠 Average",
    "poor": "🔴 Not a Good Deal",
    "insufficient_data": "Not enough historical data yet",
}


@dataclass(frozen=True)
class DealInputs:
    """Non-price signals. ``None`` means unknown (the factor is skipped, not zeroed)."""

    rating: Decimal | float | None = None
    review_count: int | None = None
    seller_name: str | None = None
    #: Sum of discount amounts of applicable offers; ``None`` = offers unknown, ``0`` = none.
    offers_total_discount: Decimal | None = None


@dataclass(frozen=True)
class FactorResult:
    key: str
    weight: float
    score: float | None  # 0-100, None when it could not be computed
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DealScore:
    score: float | None
    label: Label
    confidence: float  # share of total weight that was computable (0-1)
    is_stale: bool
    factors: tuple[FactorResult, ...] = ()
    adjustments: tuple[str, ...] = ()
    insufficient_reason: str | None = None

    @property
    def display_label(self) -> str:
        return LABEL_DISPLAY[self.label]

    def factor(self, key: str) -> FactorResult | None:
        return next((f for f in self.factors if f.key == key), None)

    def to_reason(self) -> dict:
        """JSON-serialisable breakdown for ``product_scores.score_reason``."""
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "is_stale": self.is_stale,
            "adjustments": list(self.adjustments),
            "insufficient_reason": self.insufficient_reason,
            "factors": [
                {"key": f.key, "weight": f.weight, "score": None if f.score is None else round(f.score, 2), "detail": f.detail}
                for f in self.factors
            ],
        }


def classify(score: float, params: DealParams | None = None) -> Label:
    t = (params or DealParams()).thresholds
    if score >= t.exceptional:
        return "exceptional"
    if score >= t.great:
        return "great"
    if score >= t.good:
        return "good"
    if score >= t.average:
        return "average"
    return "poor"


def _insufficient(reason: str, stats: PriceStats) -> DealScore:
    return DealScore(None, "insufficient_data", 0.0, stats.is_stale, insufficient_reason=reason)


def compute_deal_score(
    stats: PriceStats, inputs: DealInputs | None = None, config: ScoringConfig | None = None
) -> DealScore:
    cfg = config or ScoringConfig()
    dp: DealParams = cfg.deal
    qp: QualityParams = cfg.quality
    inp = inputs or DealInputs()

    if not stats.is_available or stats.current_price is None:
        return _insufficient("Product is currently unavailable", stats)
    if stats.current_suspect:
        return _insufficient("Latest price looks like invalid data", stats)
    if not stats.has_sufficient_history:
        return _insufficient("Not enough historical data yet", stats)
    reference = stats.reference(cfg.history.reference_windows_days)
    if reference is None:
        return _insufficient("Not enough historical data yet", stats)

    w = dp.weights
    ref_days, ref_price = reference
    factors: list[FactorResult] = []

    # 1. Price versus the typical (average) price over the longest reliable window.
    below_ref = stats.drop_vs_avg_pct(ref_days)
    factors.append(FactorResult(
        "historical_advantage", w.historical_advantage,
        linear(below_ref, 0, dp.historical_full_score_pct) if below_ref is not None else None,
        {"window_days": ref_days, "typical_price": str(ref_price), "pct_below_typical": below_ref},
    ))

    # 2. Recent movement: how far below the recent-window average the price sits now.
    recent = stats.drop_vs_avg_pct(dp.recent_window_days)
    factors.append(FactorResult(
        "recent_drop", w.recent_drop,
        linear(recent, 0, dp.recent_full_score_pct) if recent is not None else None,
        {"window_days": dp.recent_window_days, "pct_below_recent_avg": recent},
    ))

    # 3. Closeness to the all-time (tracked) low.
    dist = stats.distance_from_low_pct
    factors.append(FactorResult(
        "distance_from_low", w.distance_from_low,
        linear(dist, dp.low_zero_score_pct, 0) if dist is not None else None,
        {"pct_above_low": dist, "historical_low": None if stats.historical_low is None else str(stats.historical_low)},
    ))

    # 4. Product quality (rating weighted by review volume).
    quality = quality_score(inp.rating, inp.review_count, qp)
    factors.append(FactorResult(
        "product_quality", w.product_quality, quality,
        {"rating": None if inp.rating is None else float(inp.rating), "review_count": inp.review_count},
    ))

    # 5. Seller reliability from configured trusted sellers.
    seller_score = None
    if inp.seller_name:
        trusted = {s.lower() for s in dp.trusted_sellers}
        seller_score = dp.trusted_seller_score if inp.seller_name.lower() in trusted else dp.other_seller_score
    factors.append(FactorResult(
        "seller_reliability", w.seller_reliability, seller_score, {"seller": inp.seller_name}
    ))

    # 6. Extra value from available offers, as a share of the price.
    offers_score, offers_pct = None, None
    if inp.offers_total_discount is not None and stats.current_price > 0:
        offers_pct = float(inp.offers_total_discount / stats.current_price * 100)
        offers_score = linear(offers_pct, 0, dp.offers_full_score_pct)
    factors.append(FactorResult(
        "available_offers", w.available_offers, offers_score, {"offers_pct_of_price": offers_pct}
    ))

    # 7. Stability: a steady price history makes the typical price trustworthy.
    cv = stats.price_cv_pct
    factors.append(FactorResult(
        "price_stability", w.price_stability,
        linear(cv, dp.stability_worst_cv_pct, dp.stability_best_cv_pct) if cv is not None else None,
        {"coefficient_of_variation_pct": cv},
    ))

    available = [f for f in factors if f.score is not None]
    total_weight = sum(f.weight for f in available)
    if total_weight <= 0:
        return _insufficient("No scoring factors could be computed", stats)

    raw = sum(f.weight * f.score for f in available) / total_weight  # type: ignore[operator]
    confidence = total_weight / sum(f.weight for f in factors)
    score = round(raw, 2)
    adjustments: list[str] = []

    # "Exceptional" needs a price genuinely near the historical low.
    if score >= dp.thresholds.exceptional and (
        dist is None or dist > dp.exceptional_max_distance_from_low_pct
    ):
        score = round(dp.thresholds.exceptional - 0.01, 2)
        adjustments.append("capped_below_exceptional: price not near historical low")

    return DealScore(
        score=score,
        label=classify(score, dp),
        confidence=confidence,
        is_stale=stats.is_stale,
        factors=tuple(factors),
        adjustments=tuple(adjustments),
    )
