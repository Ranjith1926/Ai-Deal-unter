"""Concurrent load test for the public read API. Prints throughput and latency percentiles per endpoint.

  python tests/load/load_test.py --base http://localhost:8100 --concurrency 40 --seconds 30

Point it at a scratch stack seeded by seed_perf.sql with the rate limit raised
(RATE_LIMIT_PER_MINUTE=1000000), otherwise the limiter will (correctly) throttle a single test client.
Exit code is 1 if any endpoint exceeds the error or p95 budget, so it can gate a release.
"""
import argparse
import asyncio
import random
import statistics
import time
from collections import defaultdict

import httpx

# (label, weight, builder(max_id) -> path). Weights approximate browsing: lists and detail pages dominate.
ENDPOINTS = [
    ("GET /api/products (deal order)", 18, lambda n: "/api/products?page_size=20&sort=deal_score"),
    ("GET /api/products (filtered)", 14, lambda n: f"/api/products?category={random.choice(['mobiles', 'laptops', 'tv'])}&max_price={random.choice([10000, 30000, 60000])}&sort=price_asc&page_size=20"),
    ("GET /api/products (page N)", 6, lambda n: f"/api/products?page={random.randint(1, 200)}&page_size=24&sort=deal_score"),
    ("GET /api/search", 12, lambda n: f"/api/search?q={random.choice(['phone', 'laptop', 'brand7', 'smart tv', 'model-12'])}&page_size=20"),
    ("GET /api/deals/best", 8, lambda n: "/api/deals/best?limit=12"),
    ("GET /api/deals", 6, lambda n: "/api/deals?page_size=20"),
    ("GET /api/products/{id}", 16, lambda n: f"/api/products/{random.randint(1, n)}"),
    ("GET /api/products/{id}/prices", 10, lambda n: f"/api/products/{random.randint(1, n)}/prices?days=90"),
    ("GET /api/products/{id}/compare", 6, lambda n: f"/api/products/{random.randint(1, n)}/compare"),
    ("GET /api/categories", 4, lambda n: "/api/categories"),
]
P95_BUDGET_SECONDS = {"default": 0.5, "GET /api/products/{id}/prices": 0.8}
ERROR_BUDGET = 0.001


def pct(sorted_values: list[float], p: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * p))]


async def worker(client: httpx.AsyncClient, stop_at: float, max_id: int, results: dict, errors: dict):
    labels = [e[0] for e in ENDPOINTS]
    weights = [e[1] for e in ENDPOINTS]
    builders = {e[0]: e[2] for e in ENDPOINTS}
    while time.perf_counter() < stop_at:
        label = random.choices(labels, weights)[0]
        started = time.perf_counter()
        try:
            r = await client.get(builders[label](max_id))
            ok = r.status_code == 200
        except httpx.HTTPError:
            ok = False
        elapsed = time.perf_counter() - started
        results[label].append(elapsed)
        if not ok:
            errors[label] += 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8100")
    ap.add_argument("--concurrency", type=int, default=40)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--max-id", type=int, default=5000)
    args = ap.parse_args()

    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base, timeout=30, limits=limits) as client:
        assert (await client.get("/health/live")).status_code == 200, "API not reachable"
        # Warm up (connection pools, plan caches) so the numbers describe steady state.
        for _ in range(30):
            await client.get("/api/products?page_size=20")
        results: dict[str, list[float]] = defaultdict(list)
        errors: dict[str, int] = defaultdict(int)
        started = time.perf_counter()
        stop_at = started + args.seconds
        await asyncio.gather(*(worker(client, stop_at, args.max_id, results, errors) for _ in range(args.concurrency)))
        wall = time.perf_counter() - started

    total = sum(len(v) for v in results.values())
    print(f"\n{total} requests in {wall:.1f}s = {total / wall:.0f} req/s at concurrency {args.concurrency}\n")
    print(f"{'endpoint':34} {'n':>6} {'err%':>6} {'p50':>7} {'p95':>7} {'p99':>7} {'max':>7}")
    failed = False
    for label, *_ in ENDPOINTS:
        v = sorted(results[label])
        if not v:
            continue
        err = errors[label] / len(v)
        p95 = pct(v, 0.95)
        budget = P95_BUDGET_SECONDS.get(label, P95_BUDGET_SECONDS["default"])
        bad = err > ERROR_BUDGET or p95 > budget
        failed = failed or bad
        print(f"{label:34} {len(v):6d} {err * 100:5.2f}% {pct(v, 0.5) * 1000:6.0f}ms {p95 * 1000:6.0f}ms {pct(v, 0.99) * 1000:6.0f}ms {v[-1] * 1000:6.0f}ms {'  <-- OVER BUDGET' if bad else ''}")
    all_lat = sorted(x for v in results.values() for x in v)
    print(f"\n{'ALL':34} {total:6d} {sum(errors.values()) / total * 100:5.2f}% {statistics.median(all_lat) * 1000:6.0f}ms {pct(all_lat, 0.95) * 1000:6.0f}ms {pct(all_lat, 0.99) * 1000:6.0f}ms")
    print("\nRESULT:", "FAIL (over budget)" if failed else "PASS (all endpoints within budget)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
