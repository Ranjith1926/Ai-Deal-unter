import json
from datetime import timedelta
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import func, select

from app.models import DealEvent, Notification, PriceAlert, ProductScore
from app.services import alerts, notifications, rankings, scoring
from app.services.common import JobRun, job_log
from helpers import (
    NOW,
    add_alert,
    add_history,
    add_product_with_listing,
    add_user,
)

DEAL_HISTORY = [(60, 1, 30000), (1, 0, 23000)]  # long steady price, then a real drop


async def make_product(factory, platform="amazon", ext="A1", history=DEAL_HISTORY, **kw):
    async with factory() as s:
        product, listing = await add_product_with_listing(s, platform=platform, ext=ext, **kw)
        if history:
            await add_history(s, listing.id, history)
        await s.commit()
        return product.id, listing.id


async def score(factory, config, now=NOW):
    run = JobRun()
    await scoring.calculate_scores(factory, config, run, now)
    return run


async def latest_score(factory, pid):
    async with factory() as s:
        return await s.scalar(
            select(ProductScore).where(ProductScore.product_id == pid).order_by(ProductScore.calculated_at.desc())
        )


# ------------------------------------------------------------------- scoring
async def test_real_drop_gets_high_score_with_explanation_and_new_deal_event(factory, config):
    pid, _ = await make_product(factory, rating=Decimal("4.5"), reviews=3000)
    run = await score(factory, config)
    row = await latest_score(factory, pid)
    assert float(row.deal_score) >= 85
    reasons = row.score_reason
    assert reasons["deal"]["label"] in ("great", "exceptional")
    codes = {r["code"] for r in reasons["explanation"]}
    assert {"below_avg_30d", "at_low", "good_rating"} <= codes
    assert reasons["best_listing"]["platform"] == "amazon"
    assert reasons["stats"]["historical_low"] == "23000.00"
    json.dumps(reasons)  # fully serialisable
    async with factory() as s:
        events = (await s.scalars(select(DealEvent).where(DealEvent.event_type == "new_deal"))).all()
    assert len(events) == 1 and run.events == 1


async def test_rescoring_unchanged_data_adds_no_rows_or_events(factory, config):
    pid, _ = await make_product(factory)
    await score(factory, config)
    run = await score(factory, config, NOW + timedelta(minutes=30))
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(ProductScore)) == 1
        assert await s.scalar(select(func.count()).select_from(DealEvent)) == 1
    assert run.stored == 0


async def test_product_without_history_gets_null_score_not_a_guess(factory, config):
    pid, _ = await make_product(factory, history=[(1, 0, 1000)])
    await score(factory, config)
    row = await latest_score(factory, pid)
    assert row.deal_score is None
    assert row.score_reason["deal"]["insufficient_reason"] == "Not enough historical data yet"


async def test_constant_price_with_big_mrp_is_not_a_deal(factory, config):
    pid, _ = await make_product(factory, history=[(60, 0, 52999)])
    await score(factory, config)
    row = await latest_score(factory, pid)
    assert float(row.deal_score) < 60
    assert row.score_reason["deal"]["label"] == "poor"


async def test_cheapest_platform_is_chosen_and_explained(factory, config):
    async with factory() as s:
        product, a = await add_product_with_listing(s, platform="amazon", ext="A1")
        from app.models import ProductPlatform

        f = ProductPlatform(product_id=product.id, platform="flipkart", external_product_id="F1", url="https://x.invalid/F1")
        s.add(f)
        await s.flush()
        await add_history(s, a.id, [(60, 1, 30000), (1, 0, 26000)])
        await add_history(s, f.id, [(60, 1, 30000), (1, 0, 23000)])
        await s.commit()
        pid = product.id
    await score(factory, config)
    reason = (await latest_score(factory, pid)).score_reason
    assert reason["best_listing"]["platform"] == "flipkart"
    texts = " ".join(r["text"] for r in reason["explanation"])
    assert "Flipkart has the lowest price" in texts and "Amazon and Flipkart" in texts
    assert {p["platform"] for p in reason["platform_prices"]} == {"amazon", "flipkart"}


async def test_deal_expires_when_price_returns_to_normal(factory, config):
    pid, listing_id = await make_product(factory)
    await score(factory, config)
    async with factory() as s:
        await add_history(s, listing_id, [(0, 0, 30000)], now=NOW + timedelta(days=2))
        await s.commit()
    await score(factory, config, NOW + timedelta(days=2, hours=1))
    async with factory() as s:
        kinds = set(await s.scalars(select(DealEvent.event_type)))
    assert {"new_deal", "deal_expired"} <= kinds


async def test_value_scores_computed_for_comparable_products(factory, config):
    from app.models import Category

    async with factory() as s:
        cat = Category(name="Laptops", slug="laptops")
        s.add(cat)
        await s.flush()
        specs = [("16GB", "512GB", "Intel Core i5", 50000), ("8GB", "256GB", "Intel Core i3", 48000),
                 ("16GB", "1TB", "Intel Core i7", 90000), ("8GB", "512GB", "Intel Core i5", 45000)]
        ids = []
        for i, (ram, storage, cpu, price) in enumerate(specs):
            product, listing = await add_product_with_listing(s, name=f"L{i}", ext=f"L{i}", category_id=cat.id, rating=Decimal("4.3"), reviews=2000)
            product.specifications = {"ram": ram, "storage": storage, "processor": cpu}
            await add_history(s, listing.id, [(60, 0, price)])
            ids.append(product.id)
        await s.commit()
    await score(factory, config)
    first, second = await latest_score(factory, ids[0]), await latest_score(factory, ids[1])
    assert first.value_score is not None and second.value_score is not None
    assert first.value_score > second.value_score  # better specs at a similar price


# ------------------------------------------------------------------- alerts
async def test_alert_triggers_and_creates_notification(factory, config):
    pid, _ = await make_product(factory)
    async with factory() as s:
        user = await add_user(s, prefs={"email": True, "in_app": True})
        alert = await add_alert(s, user.id, pid, 25000)
        await s.commit()
        alert_id = alert.id
    run = JobRun()
    await alerts.process_price_alerts(factory, config, run, NOW)
    async with factory() as s:
        alert = await s.get(PriceAlert, alert_id)
        notes = (await s.scalars(select(Notification))).all()
    assert alert.triggered_at == NOW and alert.is_active is False
    assert {n.type for n in notes} == {"email", "in_app"}
    assert "₹23,000" in notes[0].message and run.events == 1


async def test_alert_not_triggered_above_target_or_for_stale_price(factory, config):
    pid, _ = await make_product(factory)
    async with factory() as s:
        user = await add_user(s)
        await add_alert(s, user.id, pid, 20000)  # price is 23,000: above target
        await s.commit()
    await alerts.process_price_alerts(factory, config, JobRun(), NOW)
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Notification)) == 0

    async with factory() as s:
        alert = await s.scalar(select(PriceAlert))
        alert.target_price = Decimal(25000)
        await s.commit()
    await alerts.process_price_alerts(factory, config, JobRun(), NOW + timedelta(days=2))  # data now stale
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Notification)) == 0
        assert (await s.scalar(select(PriceAlert))).is_active is True


async def test_alert_respects_platform_filter(factory, config):
    pid, _ = await make_product(factory, platform="amazon")
    async with factory() as s:
        user = await add_user(s)
        await add_alert(s, user.id, pid, 25000, platform="flipkart")
        await s.commit()
    await alerts.process_price_alerts(factory, config, JobRun(), NOW)
    async with factory() as s:
        assert await s.scalar(select(func.count()).select_from(Notification)) == 0


async def test_alert_defaults_to_in_app_channel(factory, config):
    pid, _ = await make_product(factory)
    async with factory() as s:
        user = await add_user(s)
        await add_alert(s, user.id, pid, 25000)
        await s.commit()
    await alerts.process_price_alerts(factory, config, JobRun(), NOW)
    async with factory() as s:
        assert [n.type for n in await s.scalars(select(Notification))] == ["in_app"]


# ------------------------------------------------------------------- notifications
async def test_dispatch_sends_in_app_and_leaves_unconfigured_channels_pending(factory):
    async with factory() as s:
        user = await add_user(s)
        for kind in ("in_app", "telegram"):
            s.add(Notification(user_id=user.id, type=kind, title="t", message="m"))
        await s.commit()
    run = JobRun()
    await notifications.dispatch_pending(factory, run, now=NOW)
    async with factory() as s:
        status = {n.type: n.status for n in await s.scalars(select(Notification))}
    assert status == {"in_app": "sent", "telegram": "pending"} and run.stored == 1


async def test_failed_channel_marks_failed_and_continues(factory):
    class Boom:
        async def send(self, notification, user):
            raise RuntimeError("smtp down")

    async with factory() as s:
        user = await add_user(s)
        for _ in range(2):
            s.add(Notification(user_id=user.id, type="email", title="t", message="m"))
        await s.commit()
    run = JobRun()
    await notifications.dispatch_pending(factory, run, channels={"email": Boom()})
    async with factory() as s:
        assert {n.status for n in await s.scalars(select(Notification))} == {"failed"}
    assert run.errors == 2


# ------------------------------------------------------------------- rankings & job log
async def test_rankings_written_to_redis(factory, config, redis_url):
    await make_product(factory)
    await score(factory, config)
    run = JobRun()
    await rankings.update_best_deals(factory, redis_url, run)
    client = Redis.from_url(redis_url)
    try:
        items = json.loads(await client.get(rankings.BEST_DEALS_KEY))
        assert await client.ttl(rankings.BEST_DEALS_KEY) > 0
    finally:
        await client.aclose()
    assert len(items) == 1 and items[0]["deal_score"] >= 85 and items[0]["best_platform"] == "amazon"


async def test_cache_cleanup_removes_only_keys_without_expiry(redis_url):
    client = Redis.from_url(redis_url)
    try:
        await client.set(f"{rankings.CACHE_PREFIX}forever", "x")
        await client.set(f"{rankings.CACHE_PREFIX}temp", "x", ex=600)
        run = JobRun()
        await rankings.cleanup_old_cache(redis_url, run)
        assert await client.exists(f"{rankings.CACHE_PREFIX}forever") == 0
        assert await client.exists(f"{rankings.CACHE_PREFIX}temp") == 1
    finally:
        await client.aclose()


async def test_job_log_records_success_and_failure(factory):
    from app.models import ProviderSyncLog

    async with job_log(factory, "amazon", "collect_prices", "job-1") as run:
        run.processed = 7
    try:
        async with job_log(factory, "flipkart", "collect_prices", "job-2") as run:
            run.processed = 3
            raise RuntimeError("provider exploded")
    except RuntimeError:
        pass
    async with factory() as s:
        logs = {l.provider: l for l in await s.scalars(select(ProviderSyncLog))}
    assert logs["amazon"].status == "success" and logs["amazon"].records_processed == 7
    assert logs["flipkart"].status == "partial" and "provider exploded" in logs["flipkart"].error_message
    assert logs["amazon"].completed_at is not None


def test_job_lock_prevents_overlap(redis_url):
    from app.services.locks import job_lock

    with job_lock(redis_url, "t", 60) as first:
        with job_lock(redis_url, "t", 60) as second:
            assert first is True and second is False
    with job_lock(redis_url, "t", 60) as again:
        assert again is True  # released after the first holder finished
