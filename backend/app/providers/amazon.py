"""Amazon India provider (skeleton).

The real integration needs Amazon Associates credentials and API access, which are not
available yet. Until it is implemented, every data method raises
``ProviderNotImplementedError`` instead of returning invented data. Implement the methods
against the official Product Advertising / Creators API and set ``implemented = True``.
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

_MSG = "Amazon integration is not implemented yet (requires Associates API access)"


class AmazonProvider(MarketplaceProvider):
    name = "amazon"
    implemented = False

    def __init__(self, access_key: str, secret_key: str, partner_tag: str) -> None:
        self._access_key, self._secret_key, self._partner_tag = access_key, secret_key, partner_tag

    @classmethod
    def from_settings(cls, s: Settings) -> "AmazonProvider | None":
        if not (s.amazon_access_key and s.amazon_secret_key and s.amazon_partner_tag):
            return None
        return cls(s.amazon_access_key, s.amazon_secret_key, s.amazon_partner_tag)

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
