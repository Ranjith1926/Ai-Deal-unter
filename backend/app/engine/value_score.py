"""Value Score: how much product you get for the money compared with similar products.

Factors: spec value (performance per rupee, ranked against comparable products), quality
(rating x review volume) and historical pricing (the deal score's price-vs-typical factor).
A pricier product can out-score a cheaper one when its specs and quality justify the price.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from app.engine.config import SpecRule, ScoringConfig
from app.engine.quality import quality_score


@dataclass(frozen=True)
class ProductProfile:
    product_id: int
    category: str | None
    price: Decimal | None
    #: Specifications merged with variant attributes, e.g. {"ram": "8GB", "storage": "256GB"}.
    attributes: dict[str, str] = field(default_factory=dict)
    rating: Decimal | float | None = None
    review_count: int | None = None
    #: 0-100 historical-advantage score from the deal engine, if available.
    historical_pricing_score: float | None = None


@dataclass(frozen=True)
class ValueFactor:
    key: str
    weight: float
    score: float | None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ValueScore:
    product_id: int
    score: float | None
    confidence: float
    factors: tuple[ValueFactor, ...] = ()
    insufficient_reason: str | None = None

    def factor(self, key: str) -> ValueFactor | None:
        return next((f for f in self.factors if f.key == key), None)

    def to_reason(self) -> dict:
        return {
            "confidence": round(self.confidence, 3),
            "insufficient_reason": self.insufficient_reason,
            "factors": [
                {"key": f.key, "weight": f.weight, "score": None if f.score is None else round(f.score, 2), "detail": f.detail}
                for f in self.factors
            ],
        }


_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _attribute(profile: ProductProfile, rule: SpecRule) -> str | None:
    lowered = {k.lower(): v for k, v in profile.attributes.items()}
    return next((lowered[k] for k in rule.keys if k in lowered), None)


def _rule_value(raw: str, rule: SpecRule) -> float | None:
    text = raw.lower()
    if rule.kind == "tier":
        # Longest keyword first so "full hd" wins over "hd".
        for keyword in sorted(rule.tiers, key=len, reverse=True):
            if keyword in text:
                return rule.tiers[keyword]
        return None
    match = _NUMBER.search(text)
    if not match:
        return None
    value = float(match.group())
    if "tb" in text:  # storage in TB -> GB so 1TB > 512GB
        value *= 1024
    return value


def _spec_points(group: Sequence[ProductProfile], rules: Sequence[SpecRule]) -> dict[int, float | None]:
    """0-100 spec index per product, normalised within the group."""
    values: dict[int, dict[int, float]] = {}  # rule index -> {product_id: value}
    for r_idx, rule in enumerate(rules):
        for prof in group:
            raw = _attribute(prof, rule)
            val = _rule_value(raw, rule) if raw else None
            if val is not None:
                values.setdefault(r_idx, {})[prof.product_id] = val

    points: dict[int, float | None] = {}
    for prof in group:
        num = den = 0.0
        for r_idx, rule in enumerate(rules):
            col = values.get(r_idx, {})
            if prof.product_id not in col:
                continue
            lo, hi = min(col.values()), max(col.values())
            norm = 50.0 if hi == lo else (col[prof.product_id] - lo) / (hi - lo) * 100.0
            num += rule.weight * norm
            den += rule.weight
        points[prof.product_id] = num / den if den else None
    return points


def _percentile_rank(value: float, population: Sequence[float]) -> float:
    if len(population) < 2:
        return 50.0
    below = sum(1 for v in population if v < value)
    ties = sum(1 for v in population if v == value) - 1
    return (below + ties / 2) / (len(population) - 1) * 100.0


def compute_value_scores(
    profiles: Sequence[ProductProfile], config: ScoringConfig | None = None
) -> dict[int, ValueScore]:
    cfg = config or ScoringConfig()
    vp = cfg.value
    w = vp.weights

    # Spec value is only meaningful against comparable products (same category).
    spec_value: dict[int, float | None] = {p.product_id: None for p in profiles}
    detail: dict[int, dict] = {p.product_id: {} for p in profiles}
    by_category: dict[str, list[ProductProfile]] = {}
    for prof in profiles:
        if prof.category:
            by_category.setdefault(prof.category, []).append(prof)

    for category, group in by_category.items():
        rules = vp.spec_rules.get(category)
        if not rules:
            continue
        points = _spec_points(group, rules)
        ratios: dict[int, float] = {}
        for prof in group:
            sp = points.get(prof.product_id)
            if sp is not None and prof.price and prof.price > 0:
                ratios[prof.product_id] = (sp + vp.spec_floor) / float(prof.price)
        if len(ratios) < vp.min_peers:
            for pid in points:
                detail[pid]["spec_note"] = f"Needs at least {vp.min_peers} comparable products"
            continue
        population = list(ratios.values())
        for pid, ratio in ratios.items():
            spec_value[pid] = _percentile_rank(ratio, population)
            detail[pid].update({"spec_points": round(points[pid] or 0, 1), "peers": len(ratios)})

    out: dict[int, ValueScore] = {}
    for prof in profiles:
        factors = (
            ValueFactor("spec_value", w.spec_value, spec_value[prof.product_id], detail[prof.product_id]),
            ValueFactor(
                "quality", w.quality, quality_score(prof.rating, prof.review_count, cfg.quality),
                {"rating": None if prof.rating is None else float(prof.rating), "review_count": prof.review_count},
            ),
            ValueFactor("historical_pricing", w.historical_pricing, prof.historical_pricing_score),
        )
        available = [f for f in factors if f.score is not None]
        total = sum(f.weight for f in available)
        confidence = total / sum(f.weight for f in factors)
        if not available or confidence < vp.min_confidence:
            out[prof.product_id] = ValueScore(
                prof.product_id, None, confidence, factors, "Not enough data to compute a reliable value score"
            )
            continue
        score = sum(f.weight * f.score for f in available) / total  # type: ignore[operator]
        out[prof.product_id] = ValueScore(prof.product_id, round(score, 2), confidence, factors)
    return out


def compare_value(a: ValueScore, b: ValueScore, name_a: str, name_b: str) -> list[str]:
    """Plain-language reasons why ``a`` scores higher (or lower) than ``b``, from stored factors."""
    if a.score is None or b.score is None:
        return ["Not enough data to compare value."]
    labels = {
        "spec_value": "performance per rupee",
        "quality": "ratings and review volume",
        "historical_pricing": "price compared with its own history",
    }
    leader, trailer, lead_name, trail_name = (a, b, name_a, name_b) if a.score >= b.score else (b, a, name_b, name_a)
    lines = [f"{lead_name} has the better value score ({leader.score:.0f} vs {trailer.score:.0f})."]
    diffs = []
    for f in leader.factors:
        other = trailer.factor(f.key)
        if f.score is not None and other is not None and other.score is not None and f.score > other.score:
            diffs.append(((f.score - other.score) * f.weight, f"{lead_name} is stronger on {labels[f.key]} ({f.score:.0f} vs {other.score:.0f})."))
    lines += [text for _, text in sorted(diffs, reverse=True)]
    return lines
