from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.models import DealEvent, ProductOffer, ProductPlatform, ProductPrice
from app.providers.base import ProviderOffer
from app.providers.errors import ProviderTimeoutError
from app.services import catalog, prices
from app.services.common import JobRun
from helpers import NOW, ScriptedProvider, add_history, add_product_with_listing, handle_for, pp


async def setup_listing(factory, platform="amazon", ext="A1", history=None):
    async with factory() as s:
        product, listing = await add_product_with_listing(s, platform=platform, ext=ext)
        if history:
            await add_history(s, listing.id, history)
        await s.commit()
        return product.id, listing.id


async def collect(factory, config, provider, now=NOW):
    run = JobRun()
    await prices.collect_prices(factory, handle_for(provider), config, run, now=now)
    return run


async def rows(factory):
    async with factory() as s:
        return (await s.scalars(select(ProductPrice).order_by(ProductPrice.captured_at, ProductPrice.id))).all()


async def events(factory, kind=None):
    async with factory() as s:
        q = select(DealEvent)
        if kind:
            q = q.where(DealEvent.event_type == kind)
        return (await s.scalars(q)).all()


async def test_first_collection_stores_and_unchanged_is_skipped(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", 1000, NOW, mrp=1500)
    run = await collect(factory, config, provider)
    assert run.processed == 1 and run.stored == 1

    provider.set_price("A1", 1000, NOW + timedelta(minutes=30), mrp=1500)
    run = await collect(factory, config, provider, NOW + timedelta(minutes=30))
    assert run.stored == 0  # unchanged: nothing worth storing

    provider.set_price("A1", 1000, NOW + timedelta(hours=7), mrp=1500)
    run = await collect(factory, config, provider, NOW + timedelta(hours=7))
    assert run.stored == 1  # heartbeat keeps history alive
    assert len(await rows(factory)) == 2


async def test_history_is_append_only(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    for i, price in enumerate([1000, 950, 900]):
        at = NOW + timedelta(hours=i)
        provider.set_price("A1", price, at)
        await collect(factory, config, provider, at)
    assert [int(r.price) for r in await rows(factory)] == [1000, 950, 900]


async def test_invalid_prices_are_rejected_and_counted(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", -5, NOW)
    run = await collect(factory, config, provider)
    assert run.invalid == 1 and run.stored == 0 and await rows(factory) == []


async def test_bad_mrp_does_not_discard_a_good_price(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", 1000, NOW, mrp=-1)
    run = await collect(factory, config, provider)
    (row,) = await rows(factory)
    assert run.stored == 1 and row.mrp is None and row.price == Decimal("1000.00")


async def test_in_stock_without_price_is_stored_as_unknown(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", None, NOW, availability="in_stock")
    await collect(factory, config, provider)
    (row,) = await rows(factory)
    assert row.price is None and row.availability == "unknown"


async def test_unavailable_item_is_recorded_without_inventing_a_price(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", None, NOW, availability="out_of_stock")
    await collect(factory, config, provider)
    (row,) = await rows(factory)
    assert row.price is None and row.availability == "out_of_stock"
    async with factory() as s:
        assert (await s.scalar(select(ProductPlatform.availability))) == "out_of_stock"


async def test_price_drop_event_and_cooldown(factory, config):
    pid, _ = await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    for i, price in enumerate([1000, 900, 800]):  # two drops within the cooldown window
        at = NOW + timedelta(hours=i)
        provider.set_price("A1", price, at)
        await collect(factory, config, provider, at)
    drops = await events(factory, "price_drop")
    assert len(drops) == 1 and drops[0].product_id == pid
    assert drops[0].price == Decimal("900.00") and drops[0].previous_price == Decimal("1000.00")


async def test_historical_low_event_requires_real_history(factory, config):
    # 20 days around 1000 with a low of 900, then a new low of 880.
    await setup_listing(factory, history=[(20, 10, 1000), (10, 9, 900), (9, 0.2, 1000)])
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", 880, NOW)
    await collect(factory, config, provider)
    kinds = {e.event_type for e in await events(factory)}
    assert {"price_drop", "historical_low"} <= kinds
    low = (await events(factory, "historical_low"))[0]
    assert low.detail["is_new_low"] is True


async def test_no_historical_low_claim_without_history(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    for i, price in enumerate([1000, 700]):
        at = NOW + timedelta(hours=i)
        provider.set_price("A1", price, at)
        await collect(factory, config, provider, at)
    assert await events(factory, "historical_low") == []
    assert len(await events(factory, "price_drop")) == 1


async def test_back_in_stock_event(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", None, NOW, availability="out_of_stock")
    await collect(factory, config, provider)
    provider.set_price("A1", 1000, NOW + timedelta(hours=1))
    await collect(factory, config, provider, NOW + timedelta(hours=1))
    assert len(await events(factory, "back_in_stock")) == 1


async def test_failing_provider_does_not_block_the_other(factory, config):
    await setup_listing(factory, "amazon", "A1")
    await setup_listing(factory, "flipkart", "F1")
    amazon, flipkart = ScriptedProvider("amazon"), ScriptedProvider("flipkart")
    amazon.fail_with = ProviderTimeoutError("amazon down")
    flipkart.set_price("F1", 500, NOW)

    bad = await collect(factory, config, amazon)
    good = await collect(factory, config, flipkart)
    assert bad.errors == 1 and "amazon down" in bad.error and bad.stored == 0
    assert good.errors == 0 and good.stored == 1


async def test_offers_added_and_ended(factory, config):
    await setup_listing(factory)
    provider = ScriptedProvider("amazon")
    provider.set_price("A1", 1000, NOW)
    provider.offers = [ProviderOffer(external_id="A1", offer_type="bank", description="5% off", discount_amount=Decimal(50))]
    await collect(factory, config, provider)
    await collect(factory, config, provider)  # unchanged set: no duplicates
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(ProductOffer)) == 1

    provider.offers = []  # the offer disappeared
    later = NOW + timedelta(hours=1)
    provider.set_price("A1", 1000, later)
    await collect(factory, config, provider, later)
    async with factory() as s:
        offer = await s.scalar(select(ProductOffer))
    assert offer.valid_until == later  # recorded as ended, not deleted


async def test_catalog_then_prices_end_to_end_with_scripted_provider(factory, config):
    provider = ScriptedProvider("amazon", [pp("A1", "Widget", brand="Acme", model_number="W1", category="gadgets")])
    await catalog.sync_catalog(factory, handle_for(provider), config, JobRun())
    provider.set_price("A1", 1234.5, NOW)
    run = await collect(factory, config, provider)
    (row,) = await rows(factory)
    assert run.stored == 1 and row.price == Decimal("1234.50") and row.data_quality == "verified"
