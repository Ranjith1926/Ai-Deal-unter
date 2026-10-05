"""Scoring configuration. Nothing in the engine hard-codes a weight or threshold.

``ScoringConfig()`` holds the defaults. The admin UI / ``app_settings`` table stores partial
overrides as JSON; apply them with ``ScoringConfig.with_overrides(...)``.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class HistoryParams(BaseModel):
    windows_days: tuple[int, ...] = (7, 14, 30, 60, 90)
    # Window averages are only reported when priced time covers this share of the window.
    min_window_coverage: float = 0.5
    min_observations: int = 3
    min_history_days: float = 7.0
    # How long an observation is assumed to hold when no later observation exists.
    max_carry_hours: float = 48.0
    stale_after_hours: float = 6.0
    # Glitch filter: prices outside [low, high] x median are ignored in history statistics.
    outlier_low_ratio: float = 0.2
    outlier_high_ratio: float = 5.0
    outlier_min_points: int = 5
    # Averages tried (in order) as the "typical price" reference.
    reference_windows_days: tuple[int, ...] = (90, 60, 30, 14)
    # An unchanged price is re-recorded at this interval, so history shows the listing was
    # still live. Must stay well below ``max_carry_hours``.
    heartbeat_hours: float = 6.0


class EventParams(BaseModel):
    min_drop_pct: float = 2.0  # smallest observation-to-observation drop that counts
    historical_low_tolerance_pct: float = 1.0  # "close to" the previous low
    new_deal_min_score: float = 70.0
    deal_expired_below_score: float = 65.0  # lower than the entry bar, so scores don't flap
    cooldown_hours: float = 12.0  # same event for the same product is not repeated sooner
    score_store_min_delta: float = 0.5
    score_store_max_age_hours: float = 24.0


class MatchParams(BaseModel):
    merge_threshold: float = 90.0  # confidence needed to treat two listings as one product


class DealWeights(BaseModel):
    historical_advantage: float = 0.35
    recent_drop: float = 0.20
    distance_from_low: float = 0.20
    product_quality: float = 0.10
    seller_reliability: float = 0.05
    available_offers: float = 0.05
    price_stability: float = 0.05

    @model_validator(mode="after")
    def _sum_to_one(self) -> "DealWeights":
        total = sum(self.model_dump().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Deal weights must sum to 1.0 (got {total:.4f})")
        return self


class DealThresholds(BaseModel):
    exceptional: float = 90
    great: float = 80
    good: float = 70
    average: float = 60

    @model_validator(mode="after")
    def _ordered(self) -> "DealThresholds":
        if not (0 <= self.average < self.good < self.great < self.exceptional <= 100):
            raise ValueError("Thresholds must satisfy 0 <= average < good < great < exceptional <= 100")
        return self


class DealParams(BaseModel):
    weights: DealWeights = Field(default_factory=DealWeights)
    thresholds: DealThresholds = Field(default_factory=DealThresholds)
    historical_full_score_pct: float = 25.0  # % below typical price that earns 100
    recent_window_days: int = 7
    recent_full_score_pct: float = 15.0
    low_zero_score_pct: float = 20.0  # % above historical low that earns 0
    offers_full_score_pct: float = 10.0
    stability_best_cv_pct: float = 2.0
    stability_worst_cv_pct: float = 15.0
    trusted_sellers: list[str] = Field(default_factory=list)
    trusted_seller_score: float = 100.0
    other_seller_score: float = 60.0
    # "Exceptional" is only allowed when the price is this close to the historical low.
    exceptional_max_distance_from_low_pct: float = 5.0


class QualityParams(BaseModel):
    rating_floor: float = 3.0  # rating that earns 0
    rating_ceiling: float = 5.0
    reviews_for_full_confidence: int = 1000


class DiscountParams(BaseModel):
    # Advertised discount exceeding the real saving by this many points is flagged.
    misleading_gap_points: float = 15.0


class SpecRule(BaseModel):
    keys: list[str]  # attribute names to look for (first present wins)
    kind: Literal["numeric", "tier"] = "numeric"
    weight: float = 1.0
    tiers: dict[str, float] = Field(default_factory=dict)  # keyword -> points (tier kind)


_PROCESSOR_TIERS = {
    "i9": 95, "ryzen 9": 95, "i7": 80, "ryzen 7": 80, "i5": 60, "ryzen 5": 60,
    "i3": 40, "ryzen 3": 40, "pentium": 25, "celeron": 20,
}
_RESOLUTION_TIERS = {"8k": 100, "4k": 70, "uhd": 70, "full hd": 40, "fhd": 40, "hd": 20}


def _default_rules() -> dict[str, list[SpecRule]]:
    return {
        "mobiles": [
            SpecRule(keys=["ram"], weight=0.35),
            SpecRule(keys=["storage"], weight=0.35),
            SpecRule(keys=["display"], weight=0.30),
        ],
        "laptops": [
            SpecRule(keys=["ram"], weight=0.3),
            SpecRule(keys=["storage"], weight=0.3),
            SpecRule(keys=["processor"], kind="tier", weight=0.4, tiers=_PROCESSOR_TIERS),
        ],
        "tv": [
            SpecRule(keys=["size"], weight=0.6),
            SpecRule(keys=["resolution"], kind="tier", weight=0.4, tiers=_RESOLUTION_TIERS),
        ],
    }


class ValueWeights(BaseModel):
    spec_value: float = 0.50
    quality: float = 0.25
    historical_pricing: float = 0.25

    @model_validator(mode="after")
    def _sum_to_one(self) -> "ValueWeights":
        total = sum(self.model_dump().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Value weights must sum to 1.0 (got {total:.4f})")
        return self


class ValueParams(BaseModel):
    weights: ValueWeights = Field(default_factory=ValueWeights)
    min_peers: int = 3
    spec_floor: float = 20.0  # keeps the weakest spec set from zeroing the ratio
    min_confidence: float = 0.5  # share of weight that must be computable
    spec_rules: dict[str, list[SpecRule]] = Field(default_factory=_default_rules)


class ScoringConfig(BaseModel):
    history: HistoryParams = Field(default_factory=HistoryParams)
    deal: DealParams = Field(default_factory=DealParams)
    quality: QualityParams = Field(default_factory=QualityParams)
    discount: DiscountParams = Field(default_factory=DiscountParams)
    value: ValueParams = Field(default_factory=ValueParams)
    events: EventParams = Field(default_factory=EventParams)
    matching: MatchParams = Field(default_factory=MatchParams)

    def with_overrides(self, overrides: dict) -> "ScoringConfig":
        """Deep-merge a partial JSON override and re-validate."""

        def merge(base: dict, extra: dict) -> dict:
            out = dict(base)
            for k, v in extra.items():
                out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
            return out

        return ScoringConfig.model_validate(merge(self.model_dump(), overrides))
