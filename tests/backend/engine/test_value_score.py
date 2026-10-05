from decimal import Decimal

import pytest

from app.engine import ProductProfile, ScoringConfig, compare_value, compute_value_scores


def laptop(pid, ram, storage, cpu, price, rating="4.3", reviews=2000, hist=50.0):
    return ProductProfile(
        pid, "laptops", Decimal(price),
        {"ram": ram, "storage": storage, "processor": cpu},
        Decimal(rating), reviews, hist,
    )


LAPTOPS = [
    laptop(1, "16GB", "512GB", "Intel Core i5", 50000),
    laptop(2, "8GB", "256GB", "Intel Core i3", 48000),
    laptop(3, "16GB", "1TB", "Intel Core i7", 90000),
    laptop(4, "8GB", "512GB", "Intel Core i5", 45000),
]


def test_better_specs_at_similar_price_win():
    scores = compute_value_scores(LAPTOPS)
    assert scores[1].factor("spec_value").score > scores[2].factor("spec_value").score
    assert scores[1].score > scores[2].score


def test_higher_priced_product_can_have_better_value():
    """Product A costs more than B but offers far more; the score reflects it."""
    a = laptop(10, "16GB", "1TB", "Intel Core i7", 52000, rating="4.6", reviews=4000)
    b = laptop(11, "8GB", "256GB", "Intel Core i3", 47000, rating="4.0", reviews=300)
    peers = [laptop(12, "8GB", "512GB", "Intel Core i5", 50000), laptop(13, "16GB", "512GB", "Intel Core i5", 60000)]
    scores = compute_value_scores([a, b, *peers])
    assert a.price > b.price
    assert scores[10].score > scores[11].score
    lines = compare_value(scores[10], scores[11], "Product A", "Product B")
    assert "Product A has the better value score" in lines[0]
    assert any("performance per rupee" in l for l in lines)


def test_terabytes_outrank_gigabytes():
    scores = compute_value_scores(LAPTOPS)
    assert scores[3].factor("spec_value").detail["spec_points"] > scores[4].factor("spec_value").detail["spec_points"]


def test_needs_enough_comparable_products():
    scores = compute_value_scores(LAPTOPS[:2])
    assert scores[1].factor("spec_value").score is None


def test_no_data_means_no_score_rather_than_a_guess():
    bare = ProductProfile(1, "laptops", Decimal(1000), {})
    s = compute_value_scores([bare])[1]
    assert s.score is None and s.insufficient_reason


def test_category_without_spec_rules_uses_quality_and_history():
    p = ProductProfile(1, "electronics", Decimal(5000), {}, Decimal("4.5"), 3000, 80.0)
    s = compute_value_scores([p])[1]
    assert s.score is not None
    assert s.factor("spec_value").score is None
    assert s.confidence == pytest.approx(0.5)


def test_peers_are_per_category():
    tv = ProductProfile(99, "tv", Decimal(30000), {"size": "55 inch", "resolution": "4K UHD"}, Decimal("4.4"), 1000, 60.0)
    scores = compute_value_scores([*LAPTOPS, tv])
    assert scores[99].factor("spec_value").score is None  # only one TV: no peers
    assert scores[1].factor("spec_value").score is not None


def test_weights_configurable_and_validated():
    cfg = ScoringConfig().with_overrides({"value": {"weights": {"spec_value": 0.0, "quality": 1.0, "historical_pricing": 0.0}}})
    s = compute_value_scores(LAPTOPS, cfg)[1]
    assert s.score == pytest.approx(s.factor("quality").score, abs=0.01)
    with pytest.raises(ValueError):
        ScoringConfig().with_overrides({"value": {"weights": {"spec_value": 0.9}}})


def test_value_reason_is_json_serialisable():
    import json

    json.dumps(compute_value_scores(LAPTOPS)[1].to_reason())
