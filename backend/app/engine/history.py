"""Price-history statistics: averages, historical low/high, drops, stability.

Averages are **time-weighted**: a price that held for 20 days counts more than one seen in a
single scrape. Gaps (unavailable periods, missing data) are excluded, never filled in. A
window average is only reported when real observations cover enough of that window.
"""
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from app.engine.config import HistoryParams

_DAY = timedelta(days=1)


@dataclass(frozen=True)
class PricePoint:
    price: Decimal | None
    captured_at: datetime
    availability: str = "in_stock"
    mrp: Decimal | None = None


@dataclass(frozen=True)
class PriceStats:
    now: datetime
    current_price: Decimal | None
    current_captured_at: datetime | None
    is_available: bool
    is_stale: bool
    #: Latest price looks like bad data (extreme outlier); do not score it.
    current_suspect: bool
    observation_count: int
    history_days: float
    has_sufficient_history: bool
    averages: dict[int, Decimal | None] = field(default_factory=dict)
    historical_low: Decimal | None = None
    historical_low_at: datetime | None = None  # most recent time the low was observed
    historical_high: Decimal | None = None
    previous_price: Decimal | None = None
    price_drop_amount: Decimal | None = None
    price_drop_pct: float | None = None
    distance_from_low_pct: float | None = None
    price_cv_pct: float | None = None

    def avg(self, days: int) -> Decimal | None:
        return self.averages.get(days)

    def drop_vs_avg_pct(self, days: int) -> float | None:
        """Percent the current price is below the N-day average (negative = above it)."""
        return pct_below(self.avg(days), self.current_price)

    def reference(self, order: Sequence[int]) -> tuple[int, Decimal] | None:
        """First available average from ``order`` as ``(window_days, price)``."""
        for days in order:
            value = self.avg(days)
            if value is not None:
                return days, value
        return None


def pct_below(reference: Decimal | None, current: Decimal | None) -> float | None:
    """How far ``current`` is below ``reference``, in percent (negative if above)."""
    if reference is None or current is None or reference <= 0:
        return None
    return float((reference - current) / reference * 100)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def compute_price_stats(
    points: Sequence[PricePoint], now: datetime, params: HistoryParams | None = None
) -> PriceStats:
    p = params or HistoryParams()
    pts = sorted((x for x in points if x.captured_at <= now), key=lambda x: x.captured_at)

    def usable(x: PricePoint) -> bool:
        return x.price is not None and x.availability == "in_stock"

    priced = [i for i, x in enumerate(pts) if usable(x)]

    # Glitch filter, applied to history statistics only.
    kept = priced
    if len(priced) >= p.outlier_min_points:
        median = statistics.median(float(pts[i].price) for i in priced)  # type: ignore[arg-type]
        kept = [
            i
            for i in priced
            if p.outlier_low_ratio * median <= float(pts[i].price) <= p.outlier_high_ratio * median  # type: ignore[arg-type]
        ]
    kept_set = set(kept)

    latest = pts[-1] if pts else None
    is_available = bool(latest and usable(latest))
    current_price = latest.price if is_available else None
    last_index = len(pts) - 1
    current_suspect = bool(is_available and last_index not in kept_set)
    is_stale = latest is None or (now - latest.captured_at) > timedelta(hours=p.stale_after_hours)

    # Time-weighted intervals: each kept observation holds until the next observation of any
    # kind, the carry limit, or ``now`` - whichever is first.
    carry = timedelta(hours=p.max_carry_hours)
    intervals: list[tuple[datetime, datetime, Decimal]] = []
    for i in kept:
        start = pts[i].captured_at
        nxt = pts[i + 1].captured_at if i + 1 < len(pts) else now
        end = min(nxt, start + carry, now)
        if end > start:
            intervals.append((start, end, pts[i].price))  # type: ignore[arg-type]

    averages: dict[int, Decimal | None] = {}
    for days in p.windows_days:
        window_start = now - days * _DAY
        total = timedelta(0)
        weighted = Decimal(0)
        for start, end, price in intervals:
            s, e = max(start, window_start), end
            if e > s:
                dur = e - s
                total += dur
                weighted += price * Decimal(dur.total_seconds())
        covered = total / (days * _DAY)
        averages[days] = (
            _quantize(weighted / Decimal(total.total_seconds()))
            if total > timedelta(0) and covered >= p.min_window_coverage
            else None
        )

    kept_prices = [pts[i].price for i in kept]  # type: ignore[misc]
    historical_low = min(kept_prices) if kept_prices else None
    historical_high = max(kept_prices) if kept_prices else None
    low_at = None
    if historical_low is not None:
        low_at = max(pts[i].captured_at for i in kept if pts[i].price == historical_low)
    history_days = (now - pts[kept[0]].captured_at) / _DAY if kept else 0.0

    # Previous distinct price before the current one.
    previous_price = drop_amount = drop_pct = None
    if is_available and not current_suspect:
        for i in reversed(kept):
            if i != last_index and pts[i].price != current_price:
                previous_price = pts[i].price
                break
        if previous_price is not None and current_price is not None:
            drop_amount = previous_price - current_price
            drop_pct = pct_below(previous_price, current_price)

    distance = None
    if is_available and not current_suspect and historical_low and current_price is not None:
        distance = float((current_price - historical_low) / historical_low * 100)

    cv = None
    recent_cut = now - 90 * _DAY
    recent_prices = [float(pts[i].price) for i in kept if pts[i].captured_at >= recent_cut]  # type: ignore[arg-type]
    if len(recent_prices) >= 3 and statistics.fmean(recent_prices) > 0:
        cv = statistics.pstdev(recent_prices) / statistics.fmean(recent_prices) * 100

    return PriceStats(
        now=now,
        current_price=current_price,
        current_captured_at=latest.captured_at if latest else None,
        is_available=is_available,
        is_stale=is_stale,
        current_suspect=current_suspect,
        observation_count=len(kept),
        history_days=history_days,
        has_sufficient_history=len(kept) >= p.min_observations and history_days >= p.min_history_days,
        averages=averages,
        historical_low=historical_low,
        historical_low_at=low_at,
        historical_high=historical_high,
        previous_price=previous_price,
        price_drop_amount=drop_amount,
        price_drop_pct=drop_pct,
        distance_from_low_pct=distance,
        price_cv_pct=cv,
    )
