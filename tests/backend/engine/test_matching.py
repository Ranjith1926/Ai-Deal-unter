from app.engine.matching import ProductIdentity as P
from app.engine.matching import match_candidate


def test_gtin_match_across_different_titles():
    existing = [P("samsung", "UA55DUE77", "9900000000059", None, "size=55inch", "samsung 55 inch tv", 7)]
    cand = P("samsung", None, "9900000000059", None, "size=55inch", "samsung 55inch 4k uhd smart television")
    r = match_candidate(cand, existing)
    assert r.product_id == 7 and r.method == "gtin" and r.confidence == 99


def test_asin_match():
    r = match_candidate(P(asin="B0ABC12345"), [P(asin="B0ABC12345", product_id=3)])
    assert r.product_id == 3 and r.method == "asin"


def test_model_number_match_requires_same_brand_and_variant():
    existing = [P("apple", "A3081", None, None, "storage=128gb", "", 1)]
    assert match_candidate(P("apple", "A3081", None, None, "storage=128gb"), existing).product_id == 1
    assert match_candidate(P("apple", "A3081", None, None, "storage=256gb"), existing).product_id is None
    assert match_candidate(P("samsung", "A3081", None, None, "storage=128gb"), existing).product_id is None


def test_variants_with_same_gtin_are_not_merged():
    existing = [P("apple", "A", "111", None, "storage=128gb", "", 1)]
    r = match_candidate(P("apple", "A", "111", None, "storage=256gb"), existing)
    assert r.product_id is None and "variant" in r.reason


def test_different_storage_variants_stay_separate():
    iphone_128 = P("apple", "A3081", None, None, "colour=black|storage=128gb", "iphone 16 128gb black", 1)
    cand = P("apple", None, None, None, "colour=black|storage=256gb", "iphone 16 256gb black")
    assert match_candidate(cand, [iphone_128]).product_id is None


def test_title_alone_never_merges():
    existing = [P("acme", None, None, None, "", "acme super widget", 5)]
    r = match_candidate(P("acme", None, None, None, "", "acme super widget"), existing)
    assert r.product_id is None
    assert r.method == "title" and r.confidence < 90  # recorded as weak evidence only


def test_threshold_is_configurable():
    from app.engine.config import MatchParams

    existing = [P("acme", None, None, None, "", "acme super widget", 5)]
    r = match_candidate(P("acme", None, None, None, "", "acme super widget"), existing, MatchParams(merge_threshold=75))
    assert r.product_id == 5


def test_no_candidates():
    r = match_candidate(P("x", "m"), [])
    assert r.product_id is None and r.confidence == 0


def test_ties_resolve_to_lowest_product_id():
    a, b = P(gtin="1", product_id=9), P(gtin="1", product_id=4)
    assert match_candidate(P(gtin="1"), [a, b]).product_id == 4


def test_empty_identifiers_never_match_each_other():
    assert match_candidate(P("", None, None, None), [P("", None, None, None, product_id=1)]).product_id is None
