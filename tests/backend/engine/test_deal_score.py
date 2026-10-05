from decimal import Decimal

import pytest

from app.engine import (
    DealInputs,
    ScoringConfig,
    analyze_discount,
    build_explanation,
    compute_deal_score,
    compute_price_stats,
    format_inr,
)
from app.engine.deal_score import classify
from app.engine.config import DealParams


def score_for(history, now, inputs=None, config=None):
    stats = compute_price_stats(history, now)
    return stats, compute_deal_score(stats, inputs, config)


# ------------------------------------------------------------------ classification
@pytest.mark.parametrize(
    "value,label",
    [(100, "exceptional"), (90, "exceptional"), (89.99, "great"), (80, "great"), (79.9, "good"),
     (70, "good"), (69.9, "average"), (60, "average"), (59.99, "poor"), (0, "poor")],
)
def test_classification_bands_match_spec(value, label):
    assert classify(value) == label


# ------------------------------------------------------------------ scoring
def test_real_price_drop_to_historical_low_scores_high(now, build_history):
    history = build_history([(60, 1, 30000), (1, 0, 23000)])
    stats, deal = score_for(history, now)
    assert deal.score is not None and deal.score >= 85
    assert deal.label in ("great", "exceptional")
    assert deal.factor("distance_from_low").score == 100
    assert deal.factor("historical_advantage").score > 90


def test_advertised_discount_alone_cannot_make_an_exceptional_deal(now, build_history):
    """MRP says 37% off, but the price has never moved: not a good deal."""
    history = build_history([(60, 0, 52999)])
    stats, deal = score_for(history, now)
    discount = analyze_discount(stats.current_price, Decimal(80000), stats)
    assert discount.advertised_discount_pct > 33  # looks like a big discount...
    assert discount.real_saving == 0  # ...but the price has always been this
    assert deal.label in ("poor", "average")
    assert deal.score < 60


def test_price_above_typical_scores_poorly(now, build_history):
    history = build_history([(60, 5, 1000), (5, 0, 1300)])
    _, deal = score_for(history, now)
    assert deal.factor("historical_advantage").score == 0
    assert deal.label == "poor"


def test_insufficient_history_gives_no_score(now, build_history):
    _, deal = score_for(build_history([(1, 0, 1000)]), now)
    assert deal.score is None and deal.label == "insufficient_data"
    assert deal.insufficient_reason == "Not enough historical data yet"
    assert deal.display_label == "Not enough historical data yet"


def test_unavailable_product_gets_no_score(now, build_history):
    history = build_history([(30, 2, 1000), (2, 0, None, "out_of_stock")])
    _, deal = score_for(history, now)
    assert deal.score is None and "unavailable" in deal.insufficient_reason


def test_invalid_latest_price_is_not_scored(now, build_history):
    from app.engine import PricePoint

    history = build_history([(30, 0.1, 1000)]) + [PricePoint(Decimal(1), now)]
    _, deal = score_for(history, now)
    assert deal.score is None and "invalid" in deal.insufficient_reason


def test_stale_deal_is_flagged_not_hidden(now, build_history):
    history = build_history([(60, 2, 30000), (2, 1, 23000)])
    _, deal = score_for(history, now)
    assert deal.score is not None and deal.is_stale


def test_missing_factors_are_renormalised_and_reduce_confidence(now, build_history):
    history = build_history([(60, 1, 30000), (1, 0, 23000)])
    _, bare = score_for(history, now)
    _, full = score_for(
        history, now,
        DealInputs(rating=Decimal("4.5"), review_count=5000, seller_name="X", offers_total_discount=Decimal(500)),
    )
    assert bare.confidence < full.confidence <= 1.0
    assert bare.factor("product_quality").score is None
    assert full.factor("product_quality").score is not None


def test_quality_depends_on_review_volume(now, build_history):
    history = build_history([(60, 1, 30000), (1, 0, 23000)])
    few = score_for(history, now, DealInputs(rating=Decimal("5.0"), review_count=3))[1]
    many = score_for(history, now, DealInputs(rating=Decimal("4.6"), review_count=5000))[1]
    assert many.factor("product_quality").score > few.factor("product_quality").score


def test_trusted_seller_scores_higher(now, build_history):
    history = build_history([(60, 1, 30000), (1, 0, 23000)])
    cfg = ScoringConfig().with_overrides({"deal": {"trusted_sellers": ["Appario Retail"]}})
    trusted = score_for(history, now, DealInputs(seller_name="appario retail"), cfg)[1]
    other = score_for(history, now, DealInputs(seller_name="Unknown Co"), cfg)[1]
    assert trusted.factor("seller_reliability").score > other.factor("seller_reliability").score


def test_weights_come_from_configuration(now, build_history):
    history = build_history([(60, 1, 30000), (1, 0, 23000)])
    base = score_for(history, now)[1]
    skewed = ScoringConfig().with_overrides(
        {"deal": {"weights": {
            "historical_advantage": 0.0, "recent_drop": 0.0, "distance_from_low": 0.0,
            "product_quality": 0.0, "seller_reliability": 0.0, "available_offers": 0.0, "price_stability": 1.0}}}
    )
    only_stability = score_for(history, now, config=skewed)[1]
    assert only_stability.score == pytest.approx(only_stability.factor("price_stability").score, abs=0.01)
    assert only_stability.score != base.score


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        ScoringConfig().with_overrides({"deal": {"weights": {"historical_advantage": 0.9}}})


def test_exceptional_requires_price_near_historical_low(now, build_history):
    history = build_history([(50, 4, 100), (4, 1, 80), (1, 0, 82)])  # 2.5% above the low
    cfg = ScoringConfig().with_overrides(
        {"deal": {"thresholds": {"exceptional": 50, "great": 40, "good": 30, "average": 20}, "exceptional_max_distance_from_low_pct": 1.0}}
    )
    _, deal = score_for(history, now, config=cfg)
    assert deal.score == 49.99
    assert any("capped_below_exceptional" in a for a in deal.adjustments)


def test_score_reason_is_json_serialisable(now, build_history):
    import json

    _, deal = score_for(build_history([(60, 1, 30000), (1, 0, 23000)]), now)
    reason = deal.to_reason()
    json.dumps(reason)
    assert {f["key"] for f in reason["factors"]} == set(DealParams().weights.model_dump())


# ------------------------------------------------------------------ fake discounts
def test_fake_discount_detection_matches_spec_example(now, build_history):
    # MRP 80,000, typical ~52,999, current 49,999: "37% off" is really ~6% vs typical.
    history = build_history([(60, 1, 52999), (1, 0, 49999)])
    stats = compute_price_stats(history, now)
    d = analyze_discount(stats.current_price, Decimal(80000), stats)
    assert round(d.advertised_discount_pct, 1) == 37.5
    assert Decimal(2900) < d.real_saving < Decimal(3000)
    assert d.is_misleading is True


def test_honest_discount_not_flagged(now, build_history):
    history = build_history([(60, 1, 1000), (1, 0, 800)])
    stats = compute_price_stats(history, now)
    d = analyze_discount(stats.current_price, Decimal(1000), stats)
    assert d.is_misleading is False


def test_missing_mrp_or_history_is_unknown_not_guessed(now, build_history):
    stats = compute_price_stats(build_history([(60, 0, 1000)]), now)
    assert analyze_discount(stats.current_price, None, stats).is_misleading is None
    short = compute_price_stats(build_history([(1, 0, 1000)]), now)
    d = analyze_discount(short.current_price, Decimal(2000), short)
    assert d.advertised_discount_pct == 50 and d.typical_price is None and d.is_misleading is None


# ------------------------------------------------------------------ explanations
def test_explanation_is_built_from_real_numbers(now, build_history):
    history = build_history([(60, 1, 30000), (1, 0, 23000)])
    stats, deal = score_for(history, now)
    disc = analyze_discount(stats.current_price, Decimal(40000), stats)
    reasons = {r.code: r for r in build_explanation(stats, deal, disc, DealInputs(rating=Decimal("4.5"), review_count=2500))}
    assert "below_avg_30d" in reasons and reasons["below_avg_30d"].positive
    assert "at_low" in reasons and "₹23,000" in reasons["at_low"].text
    assert "saving_vs_typical" in reasons
    assert "2,500" in reasons["good_rating"].text


def test_explanation_for_insufficient_data(now, build_history):
    stats, deal = score_for(build_history([(1, 0, 1000)]), now)
    codes = [r.code for r in build_explanation(stats, deal)]
    assert "insufficient" in codes and "below_avg_30d" not in codes


def test_explanation_warns_about_misleading_discount(now, build_history):
    history = build_history([(60, 1, 52999), (1, 0, 49999)])
    stats, deal = score_for(history, now)
    disc = analyze_discount(stats.current_price, Decimal(80000), stats)
    reasons = build_explanation(stats, deal, disc)
    assert any(r.code == "misleading_discount" and not r.positive for r in reasons)


def test_explanation_flags_stale_data(now, build_history):
    stats, deal = score_for(build_history([(60, 2, 30000), (2, 1, 23000)]), now)
    assert any(r.code == "stale" for r in build_explanation(stats, deal))


@pytest.mark.parametrize(
    "amount,text",
    [(0, "₹0"), (999, "₹999"), (52999, "₹52,999"), (123456, "₹1,23,456"), (12345678, "₹1,23,45,678"), (-1500, "-₹1,500")],
)
def test_indian_currency_format(amount, text):
    assert format_inr(Decimal(amount)) == text
