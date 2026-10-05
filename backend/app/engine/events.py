"""Deal-event detection (pure). Persistence and cooldowns live in the service layer."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from app.engine.config import EventParams, HistoryParams

EventType = Literal["new_deal", "price_drop", "historical_low", "deal_expired", "back_in_stock"]


@dataclass(frozen=True)
class Observation:
    """A stored or newly collected observation (just the fields detection needs)."""

    price: Decimal | None
    availability: str
    captured_at: datetime
    mrp: Decimal | None = None
    seller_name: str | None = None


@dataclass(frozen=True)
class EventSpec:
    event_type: EventType
    price: Decimal | None = None
    previous_price: Decimal | None = None
    deal_score: float | None = None
    detail: dict = field(default_factory=dict)


def _purchasable(o: Observation | None) -> bool:
    return bool(o and o.availability == "in_stock" and o.price is not None)


def should_store_observation(
    previous: Observation | None, new: Observation, params: HistoryParams | None = None
) -> bool:
    """Store when something meaningful changed, or as a periodic heartbeat. Never overwrites."""
    p = params or HistoryParams()
    if previous is None:
        return True
    if (
        previous.price != new.price
        or previous.mrp != new.mrp
        or previous.availability != new.availability
        or previous.seller_name != new.seller_name
    ):
        return True
    return new.captured_at - previous.captured_at >= timedelta(hours=p.heartbeat_hours)


def detect_price_events(
    previous: Observation | None,
    new: Observation,
    prior_low: Decimal | None,
    has_sufficient_history: bool,
    params: EventParams | None = None,
) -> list[EventSpec]:
    """Events caused by a new observation relative to the one before it."""
    p = params or EventParams()
    events: list[EventSpec] = []
    if previous is None or not _purchasable(new):
        return events

    if not _purchasable(previous):
        # Was unavailable / unpriced, is purchasable now.
        events.append(EventSpec("back_in_stock", price=new.price))
        return events

    if new.price < previous.price:  # type: ignore[operator]
        drop_pct = float((previous.price - new.price) / previous.price * 100)  # type: ignore[operator]
        if drop_pct >= p.min_drop_pct:
            events.append(EventSpec(
                "price_drop", price=new.price, previous_price=previous.price,
                detail={"drop_pct": round(drop_pct, 2)},
            ))
            if has_sufficient_history and prior_low is not None:
                limit = prior_low * Decimal(str(1 + p.historical_low_tolerance_pct / 100))
                if new.price <= limit:
                    events.append(EventSpec(
                        "historical_low", price=new.price, previous_price=previous.price,
                        detail={"prior_low": str(prior_low), "is_new_low": new.price < prior_low},
                    ))
    return events


def detect_score_events(
    previous_score: float | None,
    new_score: float | None,
    price: Decimal | None = None,
    params: EventParams | None = None,
) -> list[EventSpec]:
    """new_deal / deal_expired from a score change, with hysteresis to avoid flapping."""
    p = params or EventParams()
    if new_score is None:
        return []
    was_deal = previous_score is not None and previous_score >= p.new_deal_min_score
    if new_score >= p.new_deal_min_score and not was_deal:
        return [EventSpec("new_deal", price=price, deal_score=new_score)]
    if was_deal and new_score < p.deal_expired_below_score:
        return [EventSpec("deal_expired", price=price, deal_score=new_score,
                          detail={"previous_score": previous_score})]
    return []


def should_store_score(
    previous_score: float | None,
    previous_calculated_at: datetime | None,
    new_score: float | None,
    now: datetime,
    params: EventParams | None = None,
) -> bool:
    """Skip writing a score row when nothing meaningful changed."""
    p = params or EventParams()
    if previous_calculated_at is None:
        return True
    if (previous_score is None) != (new_score is None):
        return True
    if now - previous_calculated_at >= timedelta(hours=p.score_store_max_age_hours):
        return True
    return previous_score is not None and new_score is not None and abs(new_score - previous_score) >= p.score_store_min_delta
