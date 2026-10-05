"""Pure (database-free) price and scoring engine."""
from app.engine.config import ScoringConfig
from app.engine.deal_score import DealInputs, DealScore, compute_deal_score
from app.engine.discount import DiscountAnalysis, analyze_discount
from app.engine.explain import Reason, build_explanation, format_inr
from app.engine.history import PricePoint, PriceStats, compute_price_stats
from app.engine.normalize import (
    InvalidPriceError,
    build_variant_key,
    normalize_brand,
    normalize_price,
    normalize_title,
)
from app.engine.value_score import ProductProfile, ValueScore, compare_value, compute_value_scores

__all__ = [
    "DealInputs", "DealScore", "DiscountAnalysis", "InvalidPriceError", "PricePoint", "PriceStats",
    "ProductProfile", "Reason", "ScoringConfig", "ValueScore", "analyze_discount",
    "build_explanation", "build_variant_key", "compare_value", "compute_deal_score",
    "compute_price_stats", "compute_value_scores", "format_inr", "normalize_brand",
    "normalize_price", "normalize_title",
]
