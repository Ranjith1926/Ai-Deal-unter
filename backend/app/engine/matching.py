"""Decide whether a marketplace listing is an existing product, with a confidence score.

Strongest identifiers win; normalised-title matching is only a weak fallback and on its own
never reaches the merge threshold, so unrelated products are not merged by accident.
A variant guard stops different storage / RAM / colour / pack sizes from being merged.
"""
from dataclasses import dataclass
from typing import Iterable

from app.engine.config import MatchParams

CONF_GTIN = 99.0
CONF_ASIN = 98.0
CONF_MODEL = 95.0
CONF_TITLE = 80.0  # deliberately below the default merge threshold


@dataclass(frozen=True)
class ProductIdentity:
    """Identifying fields of a product, all already normalised."""

    brand: str = ""
    model_number: str | None = None
    gtin: str | None = None
    asin: str | None = None
    variant_key: str = ""
    normalized_title: str = ""
    product_id: int | None = None


@dataclass(frozen=True)
class MatchResult:
    product_id: int | None  # set only when confidence >= threshold
    confidence: float  # best confidence seen, even when below threshold
    method: str | None  # gtin | asin | model | title | None
    reason: str


def _variants_conflict(a: ProductIdentity, b: ProductIdentity) -> bool:
    return bool(a.variant_key) and bool(b.variant_key) and a.variant_key != b.variant_key


def _same(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a == b


def score_pair(candidate: ProductIdentity, existing: ProductIdentity) -> tuple[float, str | None, str]:
    """Confidence that two identities are the same product: ``(confidence, method, reason)``."""
    if _same(candidate.gtin, existing.gtin):
        if _variants_conflict(candidate, existing):
            return 0.0, None, "same GTIN but different variants - not merged"
        return CONF_GTIN, "gtin", "GTIN match"
    if _variants_conflict(candidate, existing):
        return 0.0, None, "different variants"
    if _same(candidate.asin, existing.asin):
        return CONF_ASIN, "asin", "ASIN match"
    if (
        _same(candidate.brand, existing.brand)
        and _same(candidate.model_number, existing.model_number)
        and candidate.variant_key == existing.variant_key
    ):
        return CONF_MODEL, "model", "brand + model number + variant match"
    if (
        _same(candidate.brand, existing.brand)
        and _same(candidate.normalized_title, existing.normalized_title)
        and candidate.variant_key == existing.variant_key
    ):
        return CONF_TITLE, "title", "title-only match (weak evidence)"
    return 0.0, None, "no matching identifiers"


def match_candidate(
    candidate: ProductIdentity,
    existing: Iterable[ProductIdentity],
    params: MatchParams | None = None,
) -> MatchResult:
    threshold = (params or MatchParams()).merge_threshold
    best: tuple[float, str | None, str, int | None] = (0.0, None, "no matching identifiers", None)
    conflict: str | None = None  # explains a refused merge (e.g. same GTIN, different variant)
    # Sorted so ties resolve deterministically to the lowest product id.
    for other in sorted(existing, key=lambda e: (e.product_id is None, e.product_id)):
        confidence, method, reason = score_pair(candidate, other)
        if confidence == 0.0 and "GTIN" in reason and conflict is None:
            conflict = reason
        if confidence > best[0]:
            best = (confidence, method, reason, other.product_id)
    confidence, method, reason, pid = best
    if confidence >= threshold:
        return MatchResult(pid, confidence, method, reason)
    return MatchResult(None, confidence, method, reason if confidence else (conflict or reason))
