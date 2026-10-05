"""Flipkart provider (skeleton).

Needs an approved Flipkart Affiliate account. Until implemented, data methods raise
``ProviderNotImplementedError`` and never return invented data.
"""
from typing import Sequence

from app.core.config import Settings
from app.providers.base import (
    MarketplaceProvider,
    ProductPage,
    ProviderOffer,
    ProviderPrice,
    ProviderProduct,
)
from app.providers.errors import ProviderNotImplementedError

_MSG = "Flipkart integration is not implemented yet (requires approved affiliate API access)"


class FlipkartProvider(MarketplaceProvider):
    name = "flipkart"
    implemented = False

    def __init__(self, affiliate_id: str, affiliate_token: str) -> None:
        self._affiliate_id, self._affiliate_token = affiliate_id, affiliate_token

    @classmethod
    def from_settings(cls, s: Settings) -> "FlipkartProvider | None":
        if not (s.flipkart_affiliate_id and s.flipkart_affiliate_token):
            return None
        return cls(s.flipkart_affiliate_id, s.flipkart_affiliate_token)

    async def list_products(
        self, category: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> ProductPage:
        raise ProviderNotImplementedError(_MSG)

    async def search_products(self, query: str, limit: int = 20) -> list[ProviderProduct]:
        raise ProviderNotImplementedError(_MSG)

    async def get_product(self, external_id: str) -> ProviderProduct | None:
        raise ProviderNotImplementedError(_MSG)

    async def get_prices(self, external_ids: Sequence[str]) -> list[ProviderPrice]:
        raise ProviderNotImplementedError(_MSG)

    async def get_offers(self, external_ids: Sequence[str]) -> list[ProviderOffer]:
        raise ProviderNotImplementedError(_MSG)

    async def get_buy_link(self, external_id: str) -> str | None:
        raise ProviderNotImplementedError(_MSG)

    async def health_check(self) -> bool:
        return False
