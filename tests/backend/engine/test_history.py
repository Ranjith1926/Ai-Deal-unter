from datetime import timedelta
from decimal import Decimal

import pytest

from app.engine import PricePoint, compute_price_stats
from app.engine.config import HistoryParams
from app.engine.history import pct_below


def test_spec_example_real_price_drop_is_20_14_percent():
    # Spec: current 22,999 vs 30-day average 28,800 -> 20.14%
    assert round(pct_below(Decimal("28800"), Decimal("22999")), 2) == 20.14


def test_constant_price_stats(now, build_history):
    stats = compute_price_stats(build_history([(30, 0, 100)]), now)
    assert stats.current_price == 100
    assert stats.avg(30) == Decimal("100.00")
    assert stats.historical_low == stats.historical_high == 100
    assert stats.distance_from_low_pct == 0
    assert stats.has_sufficient_history
    assert not stats.is_stale


def test_averages_are_time_weighted_not_sample_weighted(now):
    # 100 for 10 days, then 200 for ~10 days, but only 3 observations in total.
    pts = [
        PricePoint(Decimal(100), now - timedelta(days=20)),
        PricePoint(Decimal(200), now - timedelta(days=10)),
        PricePoint(Decimal(200), now - timedelta(hours=1)),
    ]
    stats = compute_price_stats(pts, now, HistoryParams(max_carry_hours=24 * 30))
    # Sample mean would be 166.67; time-weighted is ~150.
    assert Decimal("148") < stats.avg(30) < Decimal("152")


def test_step_change_average(now, build_history):
    pts = build_history([(30, 15, 100), (15, 0, 200)])
    stats = compute_price_stats(pts, now)
    assert Decimal("145") < stats.avg(30) < Decimal("155")
    assert stats.historical_low == 100 and stats.historical_high == 200
    assert stats.previous_price == 100 and stats.price_drop_amount == -100  # a rise, not a drop


def test_unavailable_periods_are_gaps_not_prices(now, build_history):
    pts = build_history([(30, 20, 100), (20, 10, None, "out_of_stock"), (10, 0, 100)])
    stats = compute_price_stats(pts, now)
    assert stats.avg(30) == Decimal("100.00")  # gap does not drag the average toward 0
    assert stats.is_available


def test_currently_unavailable(now, build_history):
    pts = build_history([(30, 2, 100), (2, 0, None, "out_of_stock")])
    stats = compute_price_stats(pts, now)
    assert not stats.is_available and stats.current_price is None
    assert stats.distance_from_low_pct is None and stats.price_drop_pct is None


def test_insufficient_history_reports_no_fabricated_averages(now, build_history):
    stats = compute_price_stats(build_history([(1, 0, 100)]), now)
    assert not stats.has_sufficient_history
    assert stats.avg(30) is None and stats.avg(90) is None  # not enough coverage


def test_window_average_requires_coverage(now, build_history):
    stats = compute_price_stats(build_history([(20, 0, 100)]), now)
    assert stats.avg(30) is not None  # 20/30 covered
    assert stats.avg(90) is None  # 20/90 covered, below 50%


def test_no_observations(now):
    stats = compute_price_stats([], now)
    assert stats.current_price is None and stats.observation_count == 0
    assert stats.is_stale and not stats.has_sufficient_history


def test_future_observations_ignored(now, build_history):
    pts = build_history([(10, 0, 100)]) + [PricePoint(Decimal(1), now + timedelta(days=1))]
    assert compute_price_stats(pts, now).current_price == 100


def test_price_drop_vs_previous_distinct_price(now, build_history):
    pts = build_history([(10, 1, 1000), (1, 0, 900)])
    stats = compute_price_stats(pts, now)
    assert stats.previous_price == 1000
    assert stats.price_drop_amount == 100
    assert round(stats.price_drop_pct, 1) == 10.0


def test_historical_low_records_when_it_was_seen(now, build_history):
    stats = compute_price_stats(build_history([(20, 10, 1000), (10, 5, 800), (5, 0, 880)]), now)
    assert stats.historical_low == 800
    # the low held from 10 days ago until 5 days ago; the latest observation of it is reported
    assert now - timedelta(days=5, hours=3) <= stats.historical_low_at <= now - timedelta(days=5)


def test_distance_from_historical_low(now, build_history):
    pts = build_history([(20, 10, 1000), (10, 5, 800), (5, 0, 880)])
    stats = compute_price_stats(pts, now)
    assert stats.historical_low == 800
    assert round(stats.distance_from_low_pct, 1) == 10.0


def test_outlier_glitch_prices_are_excluded_from_history(now, build_history):
    pts = build_history([(20, 10, 1000), (10, 9.9, 1), (9.9, 0, 1000)])
    stats = compute_price_stats(pts, now)
    assert stats.historical_low == 1000  # the Rs 1 glitch is not a "historical low"


def test_suspect_current_price_is_flagged(now, build_history):
    pts = build_history([(20, 0.1, 1000)]) + [PricePoint(Decimal(1), now)]
    stats = compute_price_stats(pts, now)
    assert stats.current_suspect
    assert stats.distance_from_low_pct is None and stats.price_drop_pct is None


def test_stale_data_flagged(now, build_history):
    pts = build_history([(20, 1, 1000)])  # last seen a day ago
    stats = compute_price_stats(pts, now)
    assert stats.is_stale
    assert not compute_price_stats(build_history([(20, 0, 1000)]), now).is_stale


def test_stability_cv(now, build_history):
    flat = compute_price_stats(build_history([(30, 0, 1000)]), now)
    jumpy = compute_price_stats(build_history([(30, 20, 1000), (20, 10, 1500), (10, 0, 1000)]), now)
    assert flat.price_cv_pct == 0
    assert jumpy.price_cv_pct > 10
