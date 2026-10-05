import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.models import Product, ProviderSyncLog, User
from app.services import admin as svc
from app.services.common import load_scoring_config
from helpers import signup


@pytest.fixture
async def admin(client, factory):
    """Headers for a signed-in administrator."""
    _, headers = await signup(client, "boss@example.com")
    async with factory() as s:
        await s.execute(update(User).where(User.email == "boss@example.com").values(is_admin=True))
        await s.commit()
    return headers


class FakeQueue:
    def __init__(self):
        self.sent = []

    def send(self, task, args):
        self.sent.append((task, args))
        return f"task-{len(self.sent)}"


@pytest.fixture
def queue():
    from app.main import app
    from app.services.task_queue import get_queue

    q = FakeQueue()
    app.dependency_overrides[get_queue] = lambda: q
    yield q
    app.dependency_overrides.pop(get_queue, None)


ADMIN_GETS = ["/api/admin/stats", "/api/admin/jobs", "/api/admin/categories", "/api/admin/products", "/api/admin/scoring"]


# ------------------------------------------------------------------ access control
@pytest.mark.parametrize("path", ADMIN_GETS)
async def test_admin_endpoints_reject_anonymous_and_ordinary_users(client, world, path):
    assert (await client.get(path)).status_code == 401
    _, headers = await signup(client, "ordinary@example.com")
    r = await client.get(path, headers=headers)
    assert r.status_code == 403 and r.json()["message"] == "Administrator access required"


@pytest.mark.parametrize("path", ADMIN_GETS)
async def test_admin_can_read_everything(client, world, admin, path):
    assert (await client.get(path, headers=admin)).status_code == 200


async def test_mutations_are_also_admin_only(client, world, queue):
    _, headers = await signup(client, "sneaky@example.com")
    calls = [
        ("PUT", "/api/admin/providers/amazon", {"enabled": False}), ("POST", "/api/admin/jobs/trigger", {"job": "run_pipeline"}),
        ("POST", "/api/admin/categories", {"name": "X"}), ("PATCH", f"/api/admin/products/{world['tv']}", {"is_active": False}),
        ("PUT", "/api/admin/scoring", {"overrides": {}}), ("DELETE", "/api/admin/scoring", None),
    ]
    for method, path, body in calls:
        r = await client.request(method, path, headers=headers, json=body)
        assert r.status_code == 403, (method, path)
    assert queue.sent == []


async def test_registering_cannot_grant_admin(client):
    r = await client.post("/api/auth/register", json={"email": "x@example.com", "name": "X", "password": "correct-horse-battery", "is_admin": True})
    assert r.status_code == 201 and r.json()["data"]["is_admin"] is False
    _, headers = await signup(client, "y@example.com")
    r = await client.patch("/api/me", headers=headers, json={"is_admin": True})
    assert (await client.get("/api/me", headers=headers)).json()["data"]["is_admin"] is False


async def test_make_admin_command(factory, client):
    from app.cli import _make_admin

    await signup(client, "promote@example.com")
    await _make_admin(factory, "Promote@Example.com")
    async with factory() as s:
        assert (await s.scalar(select(User.is_admin).where(User.email == "promote@example.com"))) is True
    with pytest.raises(SystemExit):
        await _make_admin(factory, "nobody@example.com")


# ------------------------------------------------------------------ statistics & providers
async def test_stats_summarise_the_platform(client, world, admin, factory):
    now = datetime.now(timezone.utc)
    async with factory() as s:
        s.add_all([
            ProviderSyncLog(provider="amazon", job_name="collect_prices", status="success", records_processed=3, started_at=now - timedelta(minutes=10), completed_at=now - timedelta(minutes=9)),
            ProviderSyncLog(provider="flipkart", job_name="collect_prices", status="failed", error_message="Timeout", started_at=now - timedelta(minutes=5), completed_at=now - timedelta(minutes=4)),
        ])
        await s.commit()
    d = (await client.get("/api/admin/stats", headers=admin)).json()["data"]
    assert d["products"] == {"total": 4, "active": 4, "amazon": 3, "flipkart": 2}
    assert d["last_24h"]["deals"] == 2 and d["last_24h"]["price_drops"] == 1 and d["last_24h"]["historical_lows"] == 1
    assert d["last_24h"]["failed_jobs"] == 1 and d["users"] >= 1 and d["alerts"] == {"active": 0, "total": 0}
    assert d["average_sync_seconds"] == pytest.approx(60, abs=1) and d["last_successful_sync_at"]
    amazon, flipkart = d["providers"]
    assert (amazon["name"], amazon["mode"], amazon["health"], amazon["failures_24h"]) == ("amazon", "demo", "healthy", 0)
    assert (flipkart["health"], flipkart["last_status"], flipkart["last_error"]) == ("attention", "failed", "Timeout")


async def test_provider_can_be_disabled_and_reenabled(client, world, admin, factory):
    r = await client.put("/api/admin/providers/amazon", headers=admin, json={"enabled": False})
    assert r.json()["data"] == {"amazon": False, "flipkart": True}
    stats = (await client.get("/api/admin/stats", headers=admin)).json()["data"]["providers"]
    assert stats[0]["enabled"] is False and stats[0]["health"] == "disabled"
    # This is the check the background jobs make before doing any work.
    async with factory() as s:
        assert await svc.is_provider_enabled(s, "amazon") is False and await svc.is_provider_enabled(s, "flipkart") is True
    await client.put("/api/admin/providers/amazon", headers=admin, json={"enabled": True})
    async with factory() as s:
        assert await svc.is_provider_enabled(s, "amazon") is True
    assert (await client.put("/api/admin/providers/croma", headers=admin, json={"enabled": False})).status_code == 404


# ------------------------------------------------------------------ jobs
async def test_trigger_jobs_queue_the_right_tasks(client, world, admin, queue):
    async def go(**body):
        return await client.post("/api/admin/jobs/trigger", headers=admin, json=body)

    r = await go(job="collect_prices", provider="amazon")
    assert r.status_code == 202 and r.json()["data"]["task_id"] == "task-1"
    await go(job="collect_prices", provider="flipkart")
    await go(job="sync_catalog", provider="flipkart")
    await go(job="recalculate_scores")
    await go(job="update_rankings")
    await go(job="run_pipeline")
    await go(job="process_alerts")
    assert queue.sent == [
        ("prices.collect_amazon", []), ("prices.collect_flipkart", []), ("catalog.sync", ["flipkart"]),
        ("scores.calculate", []), ("rankings.update", []), ("pipeline.run", []), ("alerts.process", []),
    ]


@pytest.mark.parametrize("body", [
    {"job": "collect_prices"}, {"job": "sync_catalog", "provider": "croma"}, {"job": "rm -rf"}, {}, {"job": "recalculate_scores", "provider": "ebay"},
])
async def test_trigger_validates_input_and_queues_nothing(client, world, admin, queue, body):
    assert (await client.post("/api/admin/jobs/trigger", headers=admin, json=body)).status_code == 422
    assert queue.sent == []


async def test_job_logs_filter_and_paginate(client, world, admin, factory):
    now = datetime.now(timezone.utc)
    async with factory() as s:
        for i in range(7):
            s.add(ProviderSyncLog(provider="amazon" if i % 2 else "flipkart", job_name="collect_prices", status="failed" if i == 3 else "success",
                                  error_message="Boom" if i == 3 else None, records_processed=i, started_at=now - timedelta(minutes=i), completed_at=now - timedelta(minutes=i) + timedelta(seconds=12)))
        await s.commit()
    page = await client.get("/api/admin/jobs?page_size=3", headers=admin)
    body = page.json()
    assert len(body["data"]) == 3 and body["meta"]["total"] == 7 and body["meta"]["pages"] == 3
    assert body["data"][0]["records_processed"] == 0 and body["data"][0]["duration_seconds"] == 12  # newest first
    failed = (await client.get("/api/admin/jobs?failed_only=true", headers=admin)).json()["data"]
    assert [j["error"] for j in failed] == ["Boom"]
    assert len((await client.get("/api/admin/jobs?provider=amazon", headers=admin)).json()["data"]) == 3
    assert (await client.get("/api/admin/jobs?page_size=500", headers=admin)).status_code == 422


# ------------------------------------------------------------------ categories
async def test_category_crud_and_rules(client, world, admin):
    created = await client.post("/api/admin/categories", headers=admin, json={"name": "Home Appliances"})
    cat = created.json()["data"]
    assert created.status_code == 201 and cat["slug"] == "home-appliances" and cat["product_count"] == 0
    assert (await client.post("/api/admin/categories", headers=admin, json={"name": "Again", "slug": "home-appliances"})).status_code == 409
    assert (await client.post("/api/admin/categories", headers=admin, json={"name": "!!!", "slug": "###"})).status_code == 422
    assert (await client.post("/api/admin/categories", headers=admin, json={"name": "Orphan", "parent_id": 9999})).status_code == 422

    child = (await client.post("/api/admin/categories", headers=admin, json={"name": "Washers", "parent_id": cat["id"]})).json()["data"]
    renamed = (await client.patch(f"/api/admin/categories/{cat['id']}", headers=admin, json={"name": "Appliances", "slug": "Appliances!"})).json()["data"]
    assert renamed["name"] == "Appliances" and renamed["slug"] == "appliances"
    # No cycles: a parent cannot be moved under its own child, or under itself.
    assert (await client.patch(f"/api/admin/categories/{cat['id']}", headers=admin, json={"parent_id": child["id"]})).status_code == 422
    assert (await client.patch(f"/api/admin/categories/{cat['id']}", headers=admin, json={"parent_id": cat["id"]})).status_code == 422
    # Categories in use cannot be deleted; empty ones can.
    assert (await client.delete(f"/api/admin/categories/{cat['id']}", headers=admin)).status_code == 409  # has a sub-category
    assert (await client.delete(f"/api/admin/categories/{child['id']}", headers=admin)).status_code == 200
    assert (await client.delete(f"/api/admin/categories/{cat['id']}", headers=admin)).status_code == 200
    tv_id = next(c["id"] for c in (await client.get("/api/admin/categories", headers=admin)).json()["data"] if c["slug"] == "tv")
    in_use = await client.delete(f"/api/admin/categories/{tv_id}", headers=admin)
    assert in_use.status_code == 409 and "1 product" in in_use.json()["message"]
    assert (await client.delete("/api/admin/categories/99999", headers=admin)).status_code == 404


# ------------------------------------------------------------------ products
async def test_product_management_affects_the_public_site(client, world, admin):
    listing = (await client.get("/api/admin/products?q=samsung", headers=admin)).json()["data"]
    assert len(listing) == 1 and {l["platform"] for l in listing[0]["listings"]} == {"amazon", "flipkart"} and listing[0]["category"] == "TV"

    # Hiding a product removes it from every public view.
    assert (await client.patch(f"/api/admin/products/{world['tv']}", headers=admin, json={"is_active": False})).status_code == 200
    assert (await client.get(f"/api/products/{world['tv']}")).status_code == 404
    assert world["tv"] not in [p["id"] for p in (await client.get("/api/products")).json()["data"]]
    hidden = (await client.get("/api/admin/products?active=false", headers=admin)).json()["data"]
    assert [p["id"] for p in hidden] == [world["tv"]]
    await client.patch(f"/api/admin/products/{world['tv']}", headers=admin, json={"is_active": True})
    assert (await client.get(f"/api/products/{world['tv']}")).status_code == 200


async def test_product_edit_validation_and_listing_toggle(client, world, admin):
    assert (await client.patch(f"/api/admin/products/{world['tv']}", headers=admin, json={"category_id": 99999})).status_code == 422
    assert (await client.patch("/api/admin/products/99999", headers=admin, json={"is_active": False})).status_code == 404
    assert (await client.patch(f"/api/admin/products/{world['tv']}", headers=admin, json={"name": ""})).status_code == 422
    ok = await client.patch(f"/api/admin/products/{world['tv']}", headers=admin, json={"name": "  Samsung TV 55  "})
    assert ok.status_code == 200
    assert (await client.get(f"/api/products/{world['tv']}")).json()["data"]["name"] == "Samsung TV 55"

    assert (await client.patch(f"/api/admin/listings/{world['amazon_tv_listing']}", headers=admin, json={"is_active": False})).status_code == 200
    stores = [p["platform"] for p in (await client.get(f"/api/products/{world['tv']}")).json()["data"]["platforms"]]
    assert stores == ["flipkart"]
    assert (await client.patch("/api/admin/listings/99999", headers=admin, json={"is_active": False})).status_code == 404


# ------------------------------------------------------------------ scoring configuration
async def test_scoring_settings_roundtrip_and_reach_the_workers(client, world, admin, factory):
    first = (await client.get("/api/admin/scoring", headers=admin)).json()["data"]
    assert first["customised"] is False and first["effective"]["deal"]["thresholds"]["good"] == 70

    overrides = {"deal": {"thresholds": {"good": 65}, "weights": {
        "historical_advantage": 0.40, "recent_drop": 0.15, "distance_from_low": 0.20, "product_quality": 0.10,
        "seller_reliability": 0.05, "available_offers": 0.05, "price_stability": 0.05}}}
    saved = await client.put("/api/admin/scoring", headers=admin, json={"overrides": overrides})
    data = saved.json()["data"]
    assert saved.status_code == 200 and data["customised"] and data["effective"]["deal"]["thresholds"]["good"] == 65
    assert data["effective"]["deal"]["weights"]["historical_advantage"] == 0.40
    assert data["effective"]["deal"]["thresholds"]["great"] == 80  # untouched values keep their defaults

    config = await load_scoring_config(factory)  # exactly what the background jobs load
    assert config.deal.thresholds.good == 65 and config.deal.weights.recent_drop == 0.15

    reset = (await client.delete("/api/admin/scoring", headers=admin)).json()["data"]
    assert reset["customised"] is False and (await load_scoring_config(factory)).deal.thresholds.good == 70


@pytest.mark.parametrize("overrides,needle", [
    ({"deal": {"weights": {"historical_advantage": 0.9}}}, "sum to 1.0"),
    ({"value": {"weights": {"spec_value": 0.1}}}, "sum to 1.0"),
    ({"deal": {"thresholds": {"good": "high"}}}, "deal.thresholds.good"),
    ({"deal": {"thresholds": {"good": 85}}}, "average < good < great < exceptional"),
    ({"deal": {"thresholds": {"exceptional": 120}}}, "exceptional <= 100"),
    ({"history": {"min_window_coverage": "lots"}}, "history.min_window_coverage"),
])
async def test_invalid_scoring_settings_are_refused_and_not_saved(client, world, admin, factory, overrides, needle):
    r = await client.put("/api/admin/scoring", headers=admin, json={"overrides": overrides})
    assert r.status_code == 422 and needle in " ".join(r.json()["errors"])
    assert (await client.get("/api/admin/scoring", headers=admin)).json()["data"]["customised"] is False
    assert (await load_scoring_config(factory)).deal.thresholds.good == 70


# ------------------------------------------------------------------ audit trail
async def test_every_change_is_audit_logged(client, world, admin, queue, caplog):
    with caplog.at_level(logging.INFO, logger="app.audit"):
        await client.put("/api/admin/providers/flipkart", headers=admin, json={"enabled": False})
        await client.post("/api/admin/jobs/trigger", headers=admin, json={"job": "run_pipeline"})
        await client.patch(f"/api/admin/products/{world['tv']}", headers=admin, json={"is_active": False})
        await client.get("/api/admin/stats", headers=admin)  # reads are not audited
    actions = [(r.action, r.admin_email) for r in caplog.records if r.name == "app.audit"]
    assert actions == [("provider_toggled", "boss@example.com"), ("job_triggered", "boss@example.com"), ("product_updated", "boss@example.com")]
    assert all(r.admin_id for r in caplog.records if r.name == "app.audit")


def test_every_registered_job_can_be_triggered_through_the_api():
    """The route's allowed values and the service's job registry must not drift apart."""
    from typing import get_args

    from app.api.routes.admin import JobTrigger
    from app.services.admin import JOBS

    assert set(get_args(JobTrigger.model_fields["job"].annotation)) == set(JOBS)
