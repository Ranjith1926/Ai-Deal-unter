"""Builds the active provider set from configuration.

Selection rule per platform:
1. Real provider, if credentials are set *and* the integration is implemented.
2. Otherwise a mock provider, if mocks are allowed (default: any non-production env).
3. Otherwise the platform is disabled (logged), and the rest of the system carries on.
"""
import logging
from dataclasses import dataclass
from functools import lru_cache

from app.core.config import Settings
from app.providers.amazon import AmazonProvider
from app.providers.base import MarketplaceProvider
from app.providers.flipkart import FlipkartProvider
from app.providers.mock import MockAmazonProvider, MockFlipkartProvider
from app.providers.resilience import CircuitBreaker, ProviderGuard, RateLimiter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderHandle:
    provider: MarketplaceProvider
    guard: ProviderGuard


class ProviderRegistry:
    def __init__(self, handles: dict[str, ProviderHandle]) -> None:
        self._handles = handles

    def names(self) -> list[str]:
        return sorted(self._handles)

    def get(self, name: str) -> ProviderHandle:
        try:
            return self._handles[name]
        except KeyError:
            raise KeyError(f"Provider '{name}' is not enabled") from None

    def all(self) -> list[ProviderHandle]:
        return [self._handles[n] for n in self.names()]


def _guard(name: str, s: Settings) -> ProviderGuard:
    return ProviderGuard(
        name,
        RateLimiter(rate=s.provider_requests_per_second),
        CircuitBreaker(s.provider_circuit_failure_threshold, s.provider_circuit_recovery_seconds),
        attempts=s.provider_retry_attempts,
    )


@lru_cache
def provider_modes() -> dict[str, bool]:
    """name -> is_mock for every enabled provider, from the current settings."""
    from app.core.config import get_settings

    return {h.provider.name: h.provider.is_mock for h in build_registry(get_settings()).all()}


def build_registry(s: Settings) -> ProviderRegistry:
    candidates: list[tuple[str, MarketplaceProvider | None, type[MarketplaceProvider]]] = [
        ("amazon", AmazonProvider.from_settings(s), MockAmazonProvider),
        ("flipkart", FlipkartProvider.from_settings(s), MockFlipkartProvider),
    ]
    handles: dict[str, ProviderHandle] = {}
    for name, real, mock_cls in candidates:
        provider: MarketplaceProvider | None = None
        if real is not None and getattr(real, "implemented", False):
            provider = real
        else:
            if real is not None:
                logger.warning("%s credentials set but integration is not implemented", name)
            if s.mock_providers_enabled:
                provider = mock_cls()
                logger.warning("Using MOCK provider for %s (synthetic data)", name)
        if provider is None:
            logger.error("Provider '%s' disabled: no usable integration", name)
            continue
        handles[name] = ProviderHandle(provider, _guard(name, s))
    return ProviderRegistry(handles)
