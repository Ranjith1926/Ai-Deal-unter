"""Normalisation of prices, titles, brands and variant descriptors."""
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Mapping

MAX_PLAUSIBLE_PRICE = Decimal("10000000")  # Rs 1 crore; above this the value is treated as bad data
_CENT = Decimal("0.01")


class InvalidPriceError(ValueError):
    """The value cannot be treated as a real price."""


def normalize_price(value: Decimal | int | float | str | None) -> Decimal | None:
    """Return a 2-dp ``Decimal`` rupee amount, or ``None`` when no price was given.

    Accepts values like ``"₹52,999"`` or ``"Rs. 1,299.50"``. Raises ``InvalidPriceError`` for
    non-numeric, non-finite, zero/negative or implausibly large values, so bad provider data
    is rejected instead of being stored as history.
    """
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = re.sub(r"(?i)rs\.?|inr|₹|,|\s", "", value)
        if cleaned == "":
            return None
        value = cleaned
    try:
        amount = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        raise InvalidPriceError(f"Not a number: {value!r}") from None
    if not amount.is_finite():
        raise InvalidPriceError(f"Non-finite price: {value!r}")
    if amount <= 0:
        raise InvalidPriceError(f"Price must be positive: {value!r}")
    if amount > MAX_PLAUSIBLE_PRICE:
        raise InvalidPriceError(f"Implausibly large price: {value!r}")
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def normalize_brand(brand: str | None) -> str:
    return re.sub(r"\s+", " ", (brand or "").strip()).lower()


def normalize_title(title: str) -> str:
    """Canonical lowercase form used for fuzzy matching and search.

    ``55"``, ``55 inch``, ``55-inch`` and ``55 inches`` all become ``55inch``;
    ``128 GB`` becomes ``128gb``.
    """
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"(\d+(?:\.\d+)?)\s*(?:\"|”|″|-?\s*inch(?:es)?\b)", r"\1inch", text)
    text = re.sub(r"(\d+)\s*(gb|tb|mb|kg|mah|hz|w)\b", r"\1\2", text)
    text = re.sub(r"[^\w\s.]", " ", text)
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)  # drop stray dots, keep decimals
    return re.sub(r"\s+", " ", text).strip()


_ATTRIBUTE_ALIASES = {"color": "colour"}


def build_variant_key(attributes: Mapping[str, str]) -> str:
    """Deterministic key for variant attributes, e.g. ``colour=black|storage=128gb``.

    Different storage, RAM, colour or pack size yield different keys, so those variants are
    never merged into one product.
    """
    parts = []
    for raw_key, raw_value in attributes.items():
        key = _ATTRIBUTE_ALIASES.get(raw_key.strip().lower(), raw_key.strip().lower())
        value = re.sub(r"\s+", "", raw_value.strip().lower())
        if key and value:
            parts.append(f"{key}={value}")
    return "|".join(sorted(parts))
