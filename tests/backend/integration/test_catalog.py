from sqlalchemy import func, select

from app.models import Category, Product, ProductPlatform
from app.providers.mock import MockAmazonProvider, MockFlipkartProvider
from app.services import catalog
from app.services.common import JobRun
from helpers import ScriptedProvider, handle_for, pp


async def sync_mocks(factory, config):
    for provider in (MockAmazonProvider(), MockFlipkartProvider()):
        await catalog.sync_catalog(factory, handle_for(provider), config, JobRun())


async def count(factory, model):
    async with factory() as s:
        return await s.scalar(select(func.count()).select_from(model))


async def test_same_product_on_both_platforms_is_one_product(factory, config):
    await sync_mocks(factory, config)
    # 12 distinct products; 11 listings on each platform minus the exclusives = 22 listings.
    assert await count(factory, Product) == 12
    assert await count(factory, ProductPlatform) == 22
    async with factory() as s:
        iphone = await s.scalar(select(Product).where(Product.model_number == "MOCK-IP16-128"))
        listings = (await s.scalars(select(ProductPlatform).where(ProductPlatform.product_id == iphone.id))).all()
    assert {l.platform for l in listings} == {"amazon", "flipkart"}
    second = next(l for l in listings if l.platform == "flipkart")
    assert second.match_method == "gtin" and float(second.match_confidence) == 99.0


async def test_sync_reports_new_listings_accurately(factory, config):
    first, second = JobRun(), JobRun()
    await catalog.sync_catalog(factory, handle_for(MockAmazonProvider()), config, first)
    await catalog.sync_catalog(factory, handle_for(MockAmazonProvider()), config, second)
    assert (first.processed, first.stored) == (11, 11)
    assert (second.processed, second.stored) == (11, 0)  # nothing new on the second pass


async def test_storage_variants_are_separate_products(factory, config):
    await sync_mocks(factory, config)
    async with factory() as s:
        phones = (await s.scalars(select(Product).where(Product.brand == "Apple"))).all()
    assert len(phones) == 2
    assert {p.variant_key for p in phones} == {"colour=black|storage=128gb", "colour=black|storage=256gb"}
    assert len({p.gtin for p in phones}) == 2


async def test_sync_is_idempotent(factory, config):
    await sync_mocks(factory, config)
    await sync_mocks(factory, config)
    assert await count(factory, Product) == 12 and await count(factory, ProductPlatform) == 22


async def test_categories_created_and_no_affiliate_links_for_mocks(factory, config):
    await sync_mocks(factory, config)
    async with factory() as s:
        slugs = set(await s.scalars(select(Category.slug)))
        with_affiliate = await s.scalar(select(func.count()).select_from(ProductPlatform).where(ProductPlatform.affiliate_url.is_not(None)))
    assert {"mobiles", "laptops", "tv"} <= slugs
    assert with_affiliate == 0


async def test_listing_ratings_are_stored(factory, config):
    await sync_mocks(factory, config)
    async with factory() as s:
        listing = await s.scalar(select(ProductPlatform).where(ProductPlatform.external_product_id == "MOCKB0A001"))
    assert float(listing.rating) == 4.6 and listing.review_count == 4120


async def test_title_only_similarity_does_not_merge(factory, config):
    a = ScriptedProvider("amazon", [pp("A1", "Acme Super Widget", brand="Acme")])
    b = ScriptedProvider("flipkart", [pp("F1", "Acme Super Widget", brand="Acme")])
    for p in (a, b):
        await catalog.sync_catalog(factory, handle_for(p), config, JobRun())
    assert await count(factory, Product) == 2  # weak evidence only, so kept separate


async def test_same_gtin_with_different_variants_is_not_merged(factory, config):
    a = ScriptedProvider("amazon", [pp("A1", "Phone 128", brand="Acme", gtin="12345678901", variant_attributes={"storage": "128GB"})])
    b = ScriptedProvider("flipkart", [pp("F1", "Phone 256", brand="Acme", gtin="12345678901", variant_attributes={"storage": "256GB"})])
    for p in (a, b):
        run = JobRun()
        await catalog.sync_catalog(factory, handle_for(p), config, run)
        assert run.errors == 0
    async with factory() as s:
        gtins = sorted((p.gtin or "") for p in await s.scalars(select(Product)))
    assert await count(factory, Product) == 2
    assert gtins == ["", "12345678901"]  # the unique GTIN stays with the first product only


async def test_existing_listing_is_updated_not_duplicated(factory, config):
    provider = ScriptedProvider("amazon", [pp("A1", "Widget", brand="Acme", rating=None)])
    await catalog.sync_catalog(factory, handle_for(provider), config, JobRun())
    provider.products = [pp("A1", "Widget", brand="Acme", seller_name="New Seller", review_count=10)]
    await catalog.sync_catalog(factory, handle_for(provider), config, JobRun())
    assert await count(factory, ProductPlatform) == 1
    async with factory() as s:
        listing = await s.scalar(select(ProductPlatform))
    assert listing.seller_name == "New Seller" and listing.review_count == 10
