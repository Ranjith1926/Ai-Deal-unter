"""Prometheus metrics: request rate/latency from middleware, business health gauges refreshed at scrape time."""
import time

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession

# A private registry avoids duplicate-registration errors if the app module is imported twice (tests, reload).
REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter("dh_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_LATENCY = Histogram(
    "dh_http_request_duration_seconds", "HTTP request latency", ["method", "route"], registry=REGISTRY,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 120),
)
HTTP_IN_FLIGHT = Gauge("dh_http_requests_in_flight", "Requests being served", registry=REGISTRY)

PROVIDER_ENABLED = Gauge("dh_provider_enabled", "1 if an administrator has the provider switched on", ["provider"], registry=REGISTRY)
PROVIDER_LAST_SUCCESS_AGE = Gauge(
    "dh_provider_last_success_age_seconds", "Seconds since the provider's last successful job (-1 = never)", ["provider"], registry=REGISTRY)
PROVIDER_FAILURES_24H = Gauge("dh_provider_failed_jobs_24h", "Failed or partial jobs in the last 24 hours", ["provider"], registry=REGISTRY)
PRODUCTS_ACTIVE = Gauge("dh_products_active", "Products visible on the site", registry=REGISTRY)
LISTINGS_ACTIVE = Gauge("dh_listings_active", "Tracked marketplace listings", ["provider"], registry=REGISTRY)
ALERTS_ACTIVE = Gauge("dh_price_alerts_active", "Price alerts waiting to trigger", registry=REGISTRY)
DEAL_EVENTS_24H = Gauge("dh_deal_events_24h", "Deal events detected in the last 24 hours", ["type"], registry=REGISTRY)
USERS = Gauge("dh_users", "Registered users", registry=REGISTRY)

_last_refresh = 0.0
_REFRESH_EVERY_SECONDS = 10.0


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_LATENCY.labels(method, route).observe(seconds)


async def refresh_business_gauges(session: AsyncSession, provider_modes: dict[str, bool]) -> None:
    """Update the health gauges from the database (cached for a few seconds so scrapes stay cheap)."""
    global _last_refresh
    if time.monotonic() - _last_refresh < _REFRESH_EVERY_SECONDS:
        return
    from app.services.admin import platform_stats  # local import: avoids a cycle at module load

    stats = await platform_stats(session, provider_modes)
    PRODUCTS_ACTIVE.set(stats["products"]["active"])
    ALERTS_ACTIVE.set(stats["alerts"]["active"])
    USERS.set(stats["users"])
    for event, key in (("new_deal", "deals"), ("price_drop", "price_drops"), ("historical_low", "historical_lows")):
        DEAL_EVENTS_24H.labels(event).set(stats["last_24h"][key])
    for p in stats["providers"]:
        name = p["name"]
        PROVIDER_ENABLED.labels(name).set(1 if p["enabled"] else 0)
        LISTINGS_ACTIVE.labels(name).set(p["listings"])
        PROVIDER_FAILURES_24H.labels(name).set(p["failures_24h"])
        last = p["last_success_at"]
        PROVIDER_LAST_SUCCESS_AGE.labels(name).set(-1 if last is None else max(0.0, (stats["generated_at"] - last).total_seconds()))
    _last_refresh = time.monotonic()


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
