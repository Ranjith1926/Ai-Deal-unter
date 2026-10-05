"""Read models for products, deals, comparison and price history.

Shared by the REST API and the MCP server, so both present identical data.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Money

DataStatus = Literal["verified", "estimated", "unavailable"]


class PlatformPrice(BaseModel):
    platform: str
    price: Money | None  # None = not purchasable / no price reported
    mrp: Money | None = None
    availability: str
    seller: str | None = None
    buy_url: str | None = None
    is_affiliate_link: bool = False
    updated_at: datetime | None = None
    is_stale: bool = False
    rating: float | None = None
    review_count: int | None = None


class ProductCard(BaseModel):
    id: int
    name: str
    brand: str
    category: str | None = None
    image_url: str | None = None

    current_price: Money | None = None
    previous_price: Money | None = None
    typical_price: Money | None = None
    historical_low: Money | None = None
    price_drop_pct: float | None = None
    advertised_discount_pct: float | None = None

    deal_score: float | None = None
    value_score: float | None = None
    deal_label: str = "insufficient_data"
    deal_label_text: str = "Not enough historical data yet"
    note: str | None = None
    score_calculated_at: datetime | None = None

    best_platform: str | None = None
    platforms: list[PlatformPrice] = Field(default_factory=list)
    rating: float | None = None
    review_count: int | None = None
    buy_url: str | None = None
    is_affiliate_link: bool = False

    price_updated_at: datetime | None = None
    is_stale: bool = False


class ExplanationItem(BaseModel):
    code: str
    text: str
    positive: bool


class OfferOut(BaseModel):
    platform: str
    offer_type: str
    description: str
    discount_amount: Money | None = None
    valid_until: datetime | None = None


class DiscountInfo(BaseModel):
    advertised_pct: float | None = None
    typical_price: Money | None = None
    real_saving: Money | None = None
    real_saving_pct: float | None = None
    is_misleading: bool | None = None


class ProductDetail(ProductCard):
    description: str | None = None
    model_number: str | None = None
    variant_key: str = ""
    specifications: dict[str, str] = Field(default_factory=dict)
    explanation: list[ExplanationItem] = Field(default_factory=list)
    discount: DiscountInfo | None = None
    offers: list[OfferOut] = Field(default_factory=list)
    stats: dict | None = None
    score_breakdown: dict | None = None


class DealEventInfo(BaseModel):
    event_type: str
    detected_at: datetime
    price: Money | None = None
    previous_price: Money | None = None
    detail: dict = Field(default_factory=dict)


class DealWithEvent(BaseModel):
    product: ProductCard
    event: DealEventInfo


class PricePointOut(BaseModel):
    t: datetime
    price: Money | None
    low: Money | None = None  # present on daily buckets
    high: Money | None = None
    available: bool = True


class PriceHistory(BaseModel):
    product_id: int
    days: int
    resolution: Literal["raw", "daily"]
    series: dict[str, list[PricePointOut]]
    stats: dict | None = None
    has_sufficient_history: bool
    message: str | None = None  # "Not enough historical data yet" when applicable


class FieldStatus(BaseModel):
    price: DataStatus = "verified"
    shipping: DataStatus = "unavailable"
    warranty: DataStatus = "unavailable"
    offers: DataStatus = "verified"
    price_after_offers: DataStatus = "estimated"


class PlatformComparison(BaseModel):
    platform: str
    price: Money | None
    mrp: Money | None = None
    availability: str
    seller: str | None = None
    shipping: str | None = None  # not provided by current data sources
    warranty: str | None = None
    bank_offers: list[OfferOut] = Field(default_factory=list)
    exchange_offers: list[OfferOut] = Field(default_factory=list)
    other_offers: list[OfferOut] = Field(default_factory=list)
    price_after_offers: Money | None = None  # estimate: price minus listed offer discounts
    difference_vs_cheapest: Money | None = None
    buy_url: str | None = None
    is_affiliate_link: bool = False
    updated_at: datetime | None = None
    is_stale: bool = False
    field_status: FieldStatus = Field(default_factory=FieldStatus)


class Comparison(BaseModel):
    product_id: int
    product_name: str
    platforms: list[PlatformComparison]
    best_platform: str | None = None
    price_difference: Money | None = None  # highest minus lowest live price
    summary: str


class ProductComparison(BaseModel):
    products: list[ProductDetail]
    spec_keys: list[str]
    cheapest_id: int | None = None
    best_value_id: int | None = None
    best_deal_id: int | None = None
    summary: list[str]


class BuyLink(BaseModel):
    product_id: int
    platform: str
    url: str
    is_affiliate_link: bool
    note: str | None = None


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str
    product_count: int


class Recommendation(BaseModel):
    rank: int
    score: float
    product: ProductCard
    reasons: list[str]
