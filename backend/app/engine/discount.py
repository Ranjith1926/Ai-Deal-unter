"""Fake-discount detection: advertised (MRP-based) discount vs real saving vs typical price."""
from dataclasses import dataclass
from decimal import Decimal

from app.engine.config import DiscountParams, HistoryParams
from app.engine.history import PriceStats, pct_below


@dataclass(frozen=True)
class DiscountAnalysis:
    advertised_discount_pct: float | None  # from MRP; None when MRP is missing
    typical_price: Decimal | None  # None when history is insufficient
    typical_price_window_days: int | None
    real_saving: Decimal | None  # typical - current (negative = costlier than typical)
    real_saving_pct: float | None
    gap_points: float | None  # advertised % minus real %
    is_misleading: bool | None  # None = cannot tell


def analyze_discount(
    current_price: Decimal | None,
    mrp: Decimal | None,
    stats: PriceStats,
    params: DiscountParams | None = None,
    history: HistoryParams | None = None,
) -> DiscountAnalysis:
    dp = params or DiscountParams()
    hp = history or HistoryParams()

    advertised = pct_below(mrp, current_price)
    reference = stats.reference(hp.reference_windows_days) if stats.has_sufficient_history else None

    if reference is None or current_price is None:
        return DiscountAnalysis(advertised, None, None, None, None, None, None)

    window, typical = reference
    real_saving = typical - current_price
    real_pct = pct_below(typical, current_price)
    gap = advertised - real_pct if advertised is not None and real_pct is not None else None
    return DiscountAnalysis(
        advertised_discount_pct=advertised,
        typical_price=typical,
        typical_price_window_days=window,
        real_saving=real_saving,
        real_saving_pct=real_pct,
        gap_points=gap,
        is_misleading=None if gap is None else gap >= dp.misleading_gap_points,
    )
