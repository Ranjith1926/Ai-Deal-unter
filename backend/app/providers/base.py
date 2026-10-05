"""Marketplace provider contracts.

Providers return only what the marketplace reported. A field the source does not give is
``None``; it is never guessed. The rest of the application depends on these interfaces only,
so a new marketplace is added by implementing ``MarketplaceProvider`` and registering it.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

Availability = Literal["in_stock", "out_of_stock", "discontinued", "unknown"]
DataQuality = Literal["verified", "estimated"]
OfferType = Literal["bank", "exchange", "coupon", "cashback", "no_cost_emi", "other"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ProviderProduct(_Frozen):
    external_id: str
    title: str
    url: str
    brand: str | None = None
    model_number: str | None = None
    gtin: str | None = None
    asin: str | None = None
    category: str | None = None
    image_url: str | None = None
    seller_name: str | None = None
    # Raw variant attributes as reported (e.g. {"storage": "128GB", "colour": "Black"}).
    variant_attributes: dict[str, str] = Field(default_factory=dict)
    specifications: dict[str, str] = Field(default_factory=dict)
    rating: Decimal | None = None
    review_count: int | None = None


class ProductPage(_Frozen):
    items: list[ProviderProduct]
    next_cursor: str | None = None


class ProviderPrice(_Frozen):
    external_id: str
    price: Decimal | None  # None when the marketplace shows no price
    mrp: Decimal | None = None
    currency: str = "INR"
    availability: Availability = "unknown"
    seller_name: str | None = None
    data_quality: DataQuality = "verified"
    captured_at: datetime


class ProviderOffer(_Frozen):
    external_id: str
    offer_type: OfferType
    description: str
    discount_amount: Decimal | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class ProductProvider(ABC):
    @abstractmethod
    async def list_products(
        self, category: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> ProductPage:
        """Discover products page by page, so no manual product entry is needed."""

    @abstractmethod
    async def search_products(self, query: str, limit: int = 20) -> list[ProviderProduct]: ...

    @abstractmethod
    async def get_product(self, external_id: str) -> ProviderProduct | None: ...


class PriceProvider(ABC):
    @abstractmethod
    async def get_prices(self, external_ids: Sequence[str]) -> list[ProviderPrice]:
        """Batch lookup. Unknown ids are omitted from the result."""


class OfferProvider(ABC):
    @abstractmethod
    async def get_offers(self, external_ids: Sequence[str]) -> list[ProviderOffer]: ...


class AffiliateProvider(ABC):
    @abstractmethod
    async def get_buy_link(self, external_id: str) -> str | None:
        """Affiliate URL from the provider/config, or None. Never constructed ad hoc."""


class MarketplaceProvider(ProductProvider, PriceProvider, OfferProvider, AffiliateProvider, ABC):
    """A complete marketplace integration."""

    #: Stable platform key stored in ``product_platforms.platform`` (e.g. "amazon").
    name: str
    #: True for synthetic data. Mock data must never be presented as real.
    is_mock: bool = False

    @abstractmethod
    async def health_check(self) -> bool: ...
