from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.engine import PricePoint

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def build_history():
    """Build observations from segments: (start_days_ago, end_days_ago, price[, availability])."""

    def _build(segments, step_hours=3):
        points = []
        for seg in segments:
            start, end, price, *rest = seg
            availability = rest[0] if rest else "in_stock"
            t = NOW - timedelta(days=start)
            stop = NOW - timedelta(days=end)
            while t <= stop:
                points.append(
                    PricePoint(
                        price=None if price is None else Decimal(price),
                        captured_at=t,
                        availability=availability,
                    )
                )
                t += timedelta(hours=step_hours)
        return points

    return _build
