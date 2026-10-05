from decimal import Decimal

import pytest

from app.engine import InvalidPriceError, build_variant_key, normalize_brand, normalize_price, normalize_title


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("₹52,999", "52999.00"),
        ("Rs. 1,299.50", "1299.50"),
        ("INR 499", "499.00"),
        (52999, "52999.00"),
        (1299.5, "1299.50"),
        (Decimal("10.005"), "10.01"),  # half-up, as for money
    ],
)
def test_normalize_price_parses_common_formats(raw, expected):
    assert normalize_price(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_price_is_none(raw):
    assert normalize_price(raw) is None


@pytest.mark.parametrize("raw", ["abc", "-5", 0, -1, "NaN", "Infinity", 10**9])
def test_invalid_price_rejected(raw):
    with pytest.raises(InvalidPriceError):
        normalize_price(raw)


def test_amazon_and_flipkart_titles_normalise_to_comparable_form():
    amazon = normalize_title('Samsung 55" 4K UHD Smart Television ABC123')
    other = normalize_title("Samsung 55 Inch 4K UHD Smart Television ABC123")
    assert amazon == other == "samsung 55inch 4k uhd smart television abc123"


def test_title_units_and_punctuation():
    assert normalize_title("iPhone 16 (128 GB) - Black!") == "iphone 16 128gb black"
    assert normalize_title("Laptop 15.6-inch, 16 GB") == "laptop 15.6inch 16gb"


def test_brand_normalisation():
    assert normalize_brand("  SAMSUNG ") == "samsung"
    assert normalize_brand(None) == ""


def test_variants_get_different_keys():
    a = build_variant_key({"storage": "128 GB", "colour": "Black"})
    b = build_variant_key({"storage": "256GB", "colour": "Black"})
    c = build_variant_key({"storage": "128GB", "colour": "Blue"})
    assert len({a, b, c}) == 3


def test_variant_key_is_order_and_format_insensitive():
    assert build_variant_key({"Storage": "128 GB", "color": "Black"}) == build_variant_key(
        {"colour": "black", "storage": "128gb"}
    )
    assert build_variant_key({}) == ""
