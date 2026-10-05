"""Test doubles and data builders for the integration tests."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import insert

from app.models import PriceAlert, Product, ProductPlatform, ProductPrice, User
from app.providers.base import (
    MarketplaceProvider,
    ProductPage,
    ProviderOffer,
    ProviderPrice,
    ProviderProduct,
)
from app.providers.registry import ProviderHandle
from app.providers.resilience import CircuitBreaker, ProviderGuard, RateLimiter

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
PASSWORD = "correct-horse-battery"


async def signup(client, email="shopper@example.com", password=PASSWORD):
    """Register + log in through the API; returns (tokens, auth headers)."""
    r = await client.post("/api/auth/register", json={"email": email, "name": "Shopper", "password": password})
    assert r.status_code == 201, r.text
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    tokens = r.json()["data"]
    return tokens, {"Authorization": f"Bearer {tokens['access_token']}"}


class FakeRedis:
    """In-memory stand-in for the parts of redis.asyncio the API uses (counters, TTLs, simple keys)."""

    def __init__(self) -> None:
        self.store: dict[str, int | str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key):
        value = self.store.get(key)
        return None if value is None else str(value).encode()

    async def set(self, key, value, ex=None):
        self.store[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    async def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key, seconds):
        self.ttls[key] = seconds
        return True

    async def ttl(self, key):
        return self.ttls.get(key, -1)

    async def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)
        return len(keys)

    async def aclose(self):
        return None


def make_guard(name: str = "test", attempts: int = 1) -> ProviderGuard:
    async def no_sleep(_: float) -> None:
        return None

    return ProviderGuard(
        name, RateLimiter(rate=1000, capacity=1000), CircuitBreaker(5, 60), attempts=attempts, sleep=no_sleep
    )


class ScriptedProvider(MarketplaceProvider):
    """Provider whose responses a test controls directly."""

    is_mock = True

    def __init__(self, name: str, products: list[ProviderProduct] | None = None):
        self.name = name
        self.products = products or []
        self.prices: dict[str, ProviderPrice] = {}
        self.offers: list[ProviderOffer] = []
        self.fail_with: Exception | None = None

    def set_price(self, external_id: str, price, at: datetime, availability="in_stock", mrp=None, seller="Seller"):
        self.prices[external_id] = ProviderPrice(
            external_id=external_id, price=None if price is None else Decimal(str(price)),
            mrp=None if mrp is None else Decimal(str(mrp)), availability=availability,
            seller_name=seller, captured_at=at,
        )

    async def list_products(self, category=None, cursor=None, limit=50):
        if self.fail_with:
            raise self.fail_with
        return ProductPage(items=self.products, next_cursor=None)

    async def search_products(self, query, limit=20):
        return []

    async def get_product(self, external_id):
        return None

    async def get_prices(self, external_ids):
        if self.fail_with:
            raise self.fail_with
        return [self.prices[i] for i in external_ids if i in self.prices]

    async def get_offers(self, external_ids):
        return [o for o in self.offers if o.external_id in external_ids]

    async def get_buy_link(self, external_id):
        return None

    async def health_check(self):
        return True


def handle_for(provider: MarketplaceProvider, attempts: int = 1) -> ProviderHandle:
    return ProviderHandle(provider, make_guard(provider.name, attempts))


def pp(external_id: str, title: str = "Widget", **kw) -> ProviderProduct:
    return ProviderProduct(external_id=external_id, title=title, url=f"https://example.invalid/{external_id}", **kw)


async def add_product_with_listing(session, *, name="Widget", platform="amazon", ext="X1", category_id=None,
                                   seller="Seller", rating=None, reviews=None, brand="Acme", model=None):
    product = Product(brand=brand, name=name, normalized_name=name.lower(), model_number=model, category_id=category_id)
    session.add(product)
    await session.flush()
    listing = ProductPlatform(
        product_id=product.id, platform=platform, external_product_id=ext,
        url=f"https://example.invalid/{ext}", seller_name=seller, rating=rating, review_count=reviews,
    )
    session.add(listing)
    await session.flush()
    return product, listing


def history_rows(listing_id: int, segments, now=NOW, step_hours=3):
    """ProductPrice rows from segments: (start_days_ago, end_days_ago, price[, availability])."""
    rows = []
    for seg in segments:
        start, end, price, *rest = seg
        availability = rest[0] if rest else "in_stock"
        t, stop = now - timedelta(days=start), now - timedelta(days=end)
        while t <= stop:
            rows.append(dict(
                product_platform_id=listing_id, price=None if price is None else Decimal(price),
                availability=availability, captured_at=t,
            ))
            t += timedelta(hours=step_hours)
    return rows


async def add_history(session, listing_id: int, segments, now=NOW):
    await session.execute(insert(ProductPrice), history_rows(listing_id, segments, now))


async def build_world(factory, config) -> dict:
    """A small scored catalogue ending 'now': a real deal on two platforms, a flat-price laptop,
    a laptop with a fresh drop, and a brand-new product with no history."""
    from datetime import datetime, timezone

    from app.models import Category, DealEvent, ProductOffer
    from app.services import scoring
    from app.services.common import JobRun

    now = datetime.now(timezone.utc)
    world: dict = {"now": now}
    async with factory() as s:
        tv, laptops = Category(name="TV", slug="tv"), Category(name="Laptops", slug="laptops")
        s.add_all([tv, laptops])
        await s.flush()

        async def listing(product, platform, ext, segments, final_price, **kw):
            from app.models import ProductPlatform

            l = ProductPlatform(
                product_id=product.id, platform=platform, external_product_id=ext,
                url=f"https://{platform}.invalid/{ext}", seller_name=kw.get("seller", "Seller"),
                rating=kw.get("rating"), review_count=kw.get("reviews"), availability="in_stock",
                current_price=Decimal(final_price), price_captured_at=now, affiliate_url=kw.get("affiliate"),
            )
            s.add(l)
            await s.flush()
            await add_history(s, l.id, segments, now=now)
            return l

        tv_p = Product(brand="Samsung", name="Samsung 55 inch 4K Smart TV", normalized_name="samsung 55inch 4k smart tv",
                       model_number="UA55", category_id=tv.id, specifications={"size": "55 inch"})
        l1 = Product(brand="HP", name="HP Laptop 15 i5", normalized_name="hp laptop 15 i5", model_number="HP15",
                     category_id=laptops.id, specifications={"ram": "16GB", "storage": "512GB", "processor": "Intel Core i5"})
        l2 = Product(brand="Lenovo", name="Lenovo IdeaPad Slim 3", normalized_name="lenovo ideapad slim 3", model_number="LEN3",
                     category_id=laptops.id, specifications={"ram": "8GB", "storage": "256GB", "processor": "Intel Core i3"})
        new_p = Product(brand="Acme", name="Acme Brand New Gadget", normalized_name="acme brand new gadget", category_id=None)
        s.add_all([tv_p, l1, l2, new_p])
        await s.flush()

        amazon_tv = await listing(tv_p, "amazon", "AZ-TV", [(60, 1, 30000), (1, 0, 26000)], 26000, rating=Decimal("4.4"), reviews=7600)
        flip_tv = await listing(tv_p, "flipkart", "FK-TV", [(60, 1, 30000), (1, 0, 23000)], 23000, rating=Decimal("4.5"), reviews=6100,
                                affiliate="https://affiliate.invalid/fk-tv?tag=real")
        await listing(l1, "amazon", "AZ-L1", [(60, 0, 52999)], 52999, rating=Decimal("4.1"), reviews=1800)
        await listing(l2, "flipkart", "FK-L2", [(60, 1, 40000), (1, 0, 32000)], 32000, rating=Decimal("4.0"), reviews=1500)
        await listing(new_p, "amazon", "AZ-NEW", [(1, 0, 999)], 999)

        s.add(ProductOffer(product_platform_id=flip_tv.id, offer_type="bank", description="5% off with card X",
                           discount_amount=Decimal(1150)))
        s.add(DealEvent(product_id=l2.id, event_type="price_drop", price=Decimal(32000), previous_price=Decimal(40000),
                        detail={"drop_pct": 20.0}, detected_at=now - timedelta(hours=2)))
        s.add(DealEvent(product_id=tv_p.id, event_type="historical_low", price=Decimal(23000), detected_at=now - timedelta(hours=1),
                        detail={"is_new_low": True}))
        await s.commit()
        world.update(tv=tv_p.id, laptop_flat=l1.id, laptop_drop=l2.id, new=new_p.id, flipkart_tv_listing=flip_tv.id,
                     amazon_tv_listing=amazon_tv.id)

    await scoring.calculate_scores(factory, config, JobRun(), now)
    return world


async def add_user(session, email="u@example.com", prefs=None) -> User:
    user = User(email=email, name="Test User", password_hash="x", notification_preferences=prefs or {})
    session.add(user)
    await session.flush()
    return user


async def add_alert(session, user_id, product_id, target, platform=None) -> PriceAlert:
    alert = PriceAlert(user_id=user_id, product_id=product_id, target_price=Decimal(str(target)), platform=platform)
    session.add(alert)
    await session.flush()
    return alert
