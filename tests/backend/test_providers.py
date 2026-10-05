"""Provider layer: mock data integrity, registry selection and resilience."""
from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.providers.base import MarketplaceProvider
from app.providers.errors import (
    CircuitOpenError,
    ProviderAuthError,
    ProviderNotImplementedError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from app.providers.mock import MockAmazonProvider, MockFlipkartProvider
from app.providers.registry import build_registry
from app.providers.resilience import CircuitBreaker, ProviderGuard, RateLimiter

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def fixed_clock():
    return T0


async def all_products(provider):
    page = await provider.list_products(limit=100)
    return page.items


# ---------------------------------------------------------------- mock providers
async def test_mock_providers_implement_interface():
    assert isinstance(MockAmazonProvider(), MarketplaceProvider)
    assert MockAmazonProvider().is_mock and MockFlipkartProvider().is_mock


async def test_mock_data_is_clearly_synthetic_and_has_no_affiliate_links():
    for provider in (MockAmazonProvider(), MockFlipkartProvider()):
        for p in await all_products(provider):
            assert ".invalid" in p.url
            assert p.external_id.upper().startswith("MOCK")
            assert await provider.get_buy_link(p.external_id) is None


async def test_identifiers_fit_database_columns():
    for provider in (MockAmazonProvider(), MockFlipkartProvider()):
        for p in await all_products(provider):
            assert p.asin is None or len(p.asin) <= 10
            assert p.gtin is None or len(p.gtin) <= 14


async def test_same_product_shares_identifiers_but_titles_differ():
    amazon = {p.model_number: p for p in await all_products(MockAmazonProvider())}
    flipkart = {p.model_number: p for p in await all_products(MockFlipkartProvider())}
    shared = amazon.keys() & flipkart.keys()
    assert shared
    for model in shared:
        assert amazon[model].gtin == flipkart[model].gtin
        assert amazon[model].title != flipkart[model].title


async def test_variants_have_distinct_identifiers():
    products = await all_products(MockAmazonProvider())
    iphones = [p for p in products if "iPhone 16" in p.title]
    assert len(iphones) == 2
    assert iphones[0].gtin != iphones[1].gtin
    assert iphones[0].model_number != iphones[1].model_number
    assert {p.variant_attributes["storage"] for p in iphones} == {"128GB", "256GB"}


async def test_platform_exclusive_products():
    amazon_models = {p.model_number for p in await all_products(MockAmazonProvider())}
    flipkart_models = {p.model_number for p in await all_products(MockFlipkartProvider())}
    assert amazon_models - flipkart_models
    assert flipkart_models - amazon_models


async def test_pagination_covers_everything_once():
    provider = MockAmazonProvider()
    seen, cursor = [], None
    while True:
        page = await provider.list_products(cursor=cursor, limit=3)
        seen += [p.external_id for p in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(await all_products(provider))


async def test_search_and_get_product():
    provider = MockFlipkartProvider()
    hits = await provider.search_products("samsung tv")
    assert hits and all("samsung" in h.title.lower() for h in hits)
    assert await provider.get_product(hits[0].external_id) == hits[0]
    assert await provider.get_product("does-not-exist") is None


async def test_prices_are_deterministic_for_same_time_bucket():
    provider = MockAmazonProvider(clock=fixed_clock)
    ids = [p.external_id for p in await all_products(provider)]
    first = await provider.get_prices(ids)
    second = await MockAmazonProvider(clock=fixed_clock).get_prices(ids)
    assert [p.price for p in first] == [p.price for p in second]
    assert all(p.captured_at == T0 for p in first)


async def test_unknown_ids_omitted_from_price_batch():
    assert await MockAmazonProvider().get_prices(["nope"]) == []


async def test_edge_cases_missing_mrp_and_out_of_stock():
    amazon = {p.external_id: p for p in await MockAmazonProvider(clock=fixed_clock).get_prices(
        [x.external_id for x in await all_products(MockAmazonProvider())])}
    assert any(p.mrp is None and p.price is not None for p in amazon.values())

    flip_provider = MockFlipkartProvider(clock=fixed_clock)
    flip = await flip_provider.get_prices([x.external_id for x in await all_products(flip_provider)])
    out = [p for p in flip if p.availability == "out_of_stock"]
    assert out and all(p.price is None for p in out)  # never invent a price for unavailable items


async def test_offers_reference_known_listings():
    provider = MockAmazonProvider()
    ids = [p.external_id for p in await all_products(provider)]
    offers = await provider.get_offers(ids)
    assert offers and all(o.external_id in ids for o in offers)


# ---------------------------------------------------------------- registry
def test_registry_uses_mocks_in_development():
    reg = build_registry(Settings(app_env="development"))
    assert reg.names() == ["amazon", "flipkart"]
    assert all(h.provider.is_mock for h in reg.all())


def test_registry_disables_providers_in_production_without_credentials():
    reg = build_registry(Settings(app_env="production"))
    assert reg.names() == []
    with pytest.raises(KeyError):
        reg.get("amazon")


def test_registry_never_serves_mock_when_unimplemented_credentials_in_production():
    reg = build_registry(
        Settings(app_env="production", amazon_access_key="k", amazon_secret_key="s", amazon_partner_tag="t")
    )
    assert "amazon" not in reg.names()


def test_registry_mock_override_flag():
    assert build_registry(Settings(app_env="production", use_mock_providers=True)).names() == [
        "amazon",
        "flipkart",
    ]
    assert build_registry(Settings(app_env="development", use_mock_providers=False)).names() == []


async def test_real_provider_skeletons_do_not_fabricate_data():
    from app.providers.amazon import AmazonProvider

    provider = AmazonProvider("k", "s", "t")
    with pytest.raises(ProviderNotImplementedError):
        await provider.get_prices(["x"])
    assert await provider.health_check() is False


# ---------------------------------------------------------------- resilience
class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_guard(attempts=3, threshold=5, clock=None, sleeps=None):
    clock = clock or FakeClock()
    sleeps = sleeps if sleeps is not None else []

    async def sleep(d):
        sleeps.append(d)

    guard = ProviderGuard(
        "test",
        RateLimiter(rate=1000, capacity=1000, clock=clock, sleep=sleep),
        CircuitBreaker(threshold, 60, clock=clock),
        attempts=attempts,
        base_delay=1.0,
        max_delay=8.0,
        sleep=sleep,
    )
    return guard, clock, sleeps


async def test_retries_then_succeeds_with_exponential_backoff():
    guard, _, sleeps = make_guard()
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderTimeoutError("slow")
        return "ok"

    assert await guard.call(flaky) == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] * 0.9  # roughly doubling (with jitter)
    assert 0.5 <= sleeps[0] <= 1.0 and 1.0 <= sleeps[1] <= 2.0


async def test_non_retryable_error_fails_immediately():
    guard, _, sleeps = make_guard()
    calls = {"n": 0}

    async def bad():
        calls["n"] += 1
        raise ProviderAuthError("denied")

    with pytest.raises(ProviderAuthError):
        await guard.call(bad)
    assert calls["n"] == 1 and sleeps == []


async def test_gives_up_after_max_attempts():
    guard, _, _ = make_guard(attempts=3)
    calls = {"n": 0}

    async def down():
        calls["n"] += 1
        raise ProviderTimeoutError("down")

    with pytest.raises(ProviderTimeoutError):
        await guard.call(down)
    assert calls["n"] == 3


async def test_rate_limit_retry_after_is_honoured():
    guard, _, sleeps = make_guard()
    calls = {"n": 0}

    async def limited():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderRateLimitError(retry_after=5)
        return "ok"

    assert await guard.call(limited) == "ok"
    assert sleeps == [5]


async def test_circuit_opens_then_recovers():
    guard, clock, _ = make_guard(attempts=1, threshold=2)

    async def down():
        raise ProviderTimeoutError("down")

    async def fine():
        return "ok"

    for _ in range(2):
        with pytest.raises(ProviderTimeoutError):
            await guard.call(down)
    assert guard.breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        await guard.call(fine)

    clock.t += 61  # recovery period elapsed -> half-open probe allowed
    assert guard.breaker.state == "half_open"
    assert await guard.call(fine) == "ok"
    assert guard.breaker.state == "closed"


async def test_failed_half_open_probe_reopens_circuit():
    guard, clock, _ = make_guard(attempts=1, threshold=1)

    async def down():
        raise ProviderTimeoutError("down")

    with pytest.raises(ProviderTimeoutError):
        await guard.call(down)
    clock.t += 61
    with pytest.raises(ProviderTimeoutError):
        await guard.call(down)
    assert guard.breaker.state == "open"


async def test_rate_limiter_waits_when_bucket_empty():
    clock, sleeps = FakeClock(), []

    async def sleep(d):
        sleeps.append(d)
        clock.t += d

    limiter = RateLimiter(rate=2, capacity=1, clock=clock, sleep=sleep)
    await limiter.acquire()  # uses the burst token
    await limiter.acquire()  # must wait ~0.5s
    assert sleeps and sleeps[0] == pytest.approx(0.5)
