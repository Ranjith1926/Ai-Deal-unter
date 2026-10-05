"""Mock marketplace providers backed by the synthetic catalogue.

Mock data is clearly marked: ``is_mock = True``, ``MOCK-`` identifiers, an unroutable
``.invalid`` URL, and **no affiliate links**. Prices move deterministically per 30-minute
bucket so repeated collection builds up history without randomness in tests.
"""
import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Sequence

from app.providers.base import (
    MarketplaceProvider,
    ProductPage,
    ProviderOffer,
    ProviderPrice,
    ProviderProduct,
)
from app.providers.mock_catalog import CATALOG, MockItem, MockListing

BUCKET_SECONDS = 30 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MockMarketplaceProvider(MarketplaceProvider):
    is_mock = True

    def __init__(self, name: str, clock: Callable[[], datetime] = _utcnow) -> None:
        self.name = name
        self._clock = clock
        self._items: dict[str, tuple[MockItem, MockListing]] = {}
        for item in CATALOG:
            listing: MockListing | None = getattr(item, name, None)
            if listing is not None:
                self._items[listing.external_id] = (item, listing)

    # -- products ---------------------------------------------------------------------
    def _to_product(self, item: MockItem, listing: MockListing) -> ProviderProduct:
        return ProviderProduct(
            external_id=listing.external_id,
            title=listing.title,
            url=f"https://mock.invalid/{self.name}/{listing.external_id}",
            brand=item.brand,
            model_number=item.model_number,
            gtin=item.gtin,
            asin=listing.asin,
            category=item.category,
            seller_name=listing.seller,
            variant_attributes=dict(item.variant),
            specifications=dict(item.specs),
            rating=Decimal(listing.rating) if listing.rating else None,
            review_count=listing.review_count,
        )

    async def list_products(
        self, category: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> ProductPage:
        rows = [
            self._to_product(i, l)
            for i, l in self._items.values()
            if category is None or i.category == category
        ]
        start = int(cursor) if cursor else 0
        page = rows[start : start + limit]
        nxt = str(start + limit) if start + limit < len(rows) else None
        return ProductPage(items=page, next_cursor=nxt)

    async def search_products(self, query: str, limit: int = 20) -> list[ProviderProduct]:
        terms = query.lower().split()
        hits = [
            self._to_product(i, l)
            for i, l in self._items.values()
            if all(t in f"{l.title} {i.brand} {i.model_number}".lower() for t in terms)
        ]
        return hits[:limit]

    async def get_product(self, external_id: str) -> ProviderProduct | None:
        entry = self._items.get(external_id)
        return self._to_product(*entry) if entry else None

    # -- prices & offers --------------------------------------------------------------
    def _price_now(self, listing: MockListing, now: datetime) -> Decimal:
        bucket = int(now.timestamp() // BUCKET_SECONDS)
        rng = random.Random(f"{self.name}:{listing.external_id}:{bucket}")
        factor = 1 + rng.uniform(-0.05, 0.04)
        if rng.random() < 0.06:  # occasional genuine-looking dip
            factor -= rng.uniform(0.10, 0.20)
        return Decimal(round(listing.base_price * factor))

    async def get_prices(self, external_ids: Sequence[str]) -> list[ProviderPrice]:
        now = self._clock()
        out: list[ProviderPrice] = []
        for ext_id in external_ids:
            entry = self._items.get(ext_id)
            if entry is None:
                continue
            _, listing = entry
            in_stock = listing.availability == "in_stock"
            out.append(
                ProviderPrice(
                    external_id=ext_id,
                    price=self._price_now(listing, now) if in_stock else None,
                    mrp=Decimal(listing.mrp) if listing.mrp else None,
                    availability=listing.availability,  # type: ignore[arg-type]
                    seller_name=listing.seller,
                    data_quality="verified",  # the provider (mock) reported it
                    captured_at=now,
                )
            )
        return out

    async def get_offers(self, external_ids: Sequence[str]) -> list[ProviderOffer]:
        offers: list[ProviderOffer] = []
        for ext_id in external_ids:
            entry = self._items.get(ext_id)
            if entry is None or entry[1].base_price < 20000:
                continue
            offers.append(
                ProviderOffer(
                    external_id=ext_id,
                    offer_type="bank",
                    description="Mock bank offer: 5% instant discount on selected cards",
                    discount_amount=Decimal(round(entry[1].base_price * 0.05)),
                )
            )
        return offers

    async def get_buy_link(self, external_id: str) -> str | None:
        return None  # mock data never produces affiliate links

    async def health_check(self) -> bool:
        return True


class MockAmazonProvider(MockMarketplaceProvider):
    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        super().__init__("amazon", clock)


class MockFlipkartProvider(MockMarketplaceProvider):
    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        super().__init__("flipkart", clock)
