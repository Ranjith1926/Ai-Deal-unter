"""Plain-language deal explanations built strictly from computed statistics."""
from dataclasses import dataclass
from decimal import Decimal

from app.engine.config import ScoringConfig
from app.engine.deal_score import DealInputs, DealScore
from app.engine.discount import DiscountAnalysis
from app.engine.history import PriceStats


@dataclass(frozen=True)
class Reason:
    code: str
    text: str
    positive: bool


def format_inr(amount: Decimal | float | int) -> str:
    """Rupees with Indian digit grouping, e.g. ``₹1,23,456``."""
    value = Decimal(amount).quantize(Decimal("1"))
    sign = "-" if value < 0 else ""
    digits = str(abs(int(value)))
    head, tail = digits[:-3], digits[-3:]
    if head:
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        tail = ",".join(groups) + "," + tail
    return f"{sign}₹{tail}"


MIN_PCT_TO_MENTION = 3.0
NEAR_LOW_PCT = 3.0


def build_explanation(
    stats: PriceStats,
    deal: DealScore,
    discount: DiscountAnalysis | None = None,
    inputs: DealInputs | None = None,
    config: ScoringConfig | None = None,
) -> list[Reason]:
    cfg = config or ScoringConfig()
    reasons: list[Reason] = []

    if stats.is_stale:
        reasons.append(Reason("stale", "Price data may be outdated", False))
    if deal.score is None:
        reasons.append(Reason("insufficient", deal.insufficient_reason or "Not enough historical data yet", False))
        return reasons

    for days in (30, 90):
        pct = stats.drop_vs_avg_pct(days)
        if pct is not None and pct >= MIN_PCT_TO_MENTION:
            reasons.append(Reason(f"below_avg_{days}d", f"{pct:.0f}% below the {days}-day average", True))
        elif pct is not None and pct <= -MIN_PCT_TO_MENTION:
            reasons.append(Reason(f"above_avg_{days}d", f"{abs(pct):.0f}% above the {days}-day average", False))

    dist = stats.distance_from_low_pct
    if dist is not None and stats.historical_low is not None:
        if dist <= 0.0:
            reasons.append(Reason("at_low", f"Matches the lowest price we have tracked ({format_inr(stats.historical_low)})", True))
        elif dist <= NEAR_LOW_PCT:
            reasons.append(Reason("near_low", f"Within {dist:.1f}% of the lowest tracked price ({format_inr(stats.historical_low)})", True))

    if stats.price_drop_amount and stats.price_drop_amount > 0 and stats.price_drop_pct is not None:
        reasons.append(Reason(
            "recent_drop",
            f"Down {format_inr(stats.price_drop_amount)} ({stats.price_drop_pct:.0f}%) from the previous price",
            True,
        ))

    if discount and discount.real_saving is not None and discount.real_saving > 0 and discount.typical_price:
        reasons.append(Reason(
            "saving_vs_typical",
            f"{format_inr(discount.real_saving)} cheaper than the typical price of {format_inr(discount.typical_price)}",
            True,
        ))
    if discount and discount.is_misleading and discount.advertised_discount_pct is not None:
        reasons.append(Reason(
            "misleading_discount",
            f"Advertised {discount.advertised_discount_pct:.0f}% discount overstates the real saving"
            + (f" ({discount.real_saving_pct:.0f}% vs typical price)" if discount.real_saving_pct is not None else ""),
            False,
        ))

    inp = inputs
    if inp and inp.rating is not None and inp.review_count:
        if float(inp.rating) >= 4.0 and inp.review_count >= 100:
            reasons.append(Reason("good_rating", f"Rated {float(inp.rating):.1f}/5 by {inp.review_count:,} buyers", True))
        elif float(inp.rating) < 3.5:
            reasons.append(Reason("low_rating", f"Low rating: {float(inp.rating):.1f}/5", False))
    return reasons
