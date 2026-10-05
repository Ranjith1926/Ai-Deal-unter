"""Developer commands.  Usage:  python -m app.cli <command>

  bootstrap       sync catalogues, collect prices once, calculate scores and rankings
  seed-history    DEV ONLY: backfill synthetic price history for MOCK providers so the
                  scoring engine has data before real history accumulates
"""
import argparse
import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import worker_session_factory
from app.models import ProductPlatform
from app.providers.mock import MockMarketplaceProvider
from app.providers.registry import build_registry
from app.services import catalog, prices, rankings, scoring
from app.services.common import JobRun, SessionFactory, load_scoring_config, utcnow


async def _bootstrap(factory: SessionFactory) -> None:
    settings = get_settings()
    config = await load_scoring_config(factory)
    registry = build_registry(settings)
    for handle in registry.all():
        run = JobRun()
        await catalog.sync_catalog(factory, handle, config, run)
        print(f"{handle.provider.name}: catalogue synced ({run.stored} new listings)")
    for handle in registry.all():
        run = JobRun()
        await prices.collect_prices(factory, handle, config, run, settings.price_batch_size)
        print(f"{handle.provider.name}: {run.processed} prices processed, {run.stored} stored, {run.events} events")
    run = JobRun()
    await scoring.calculate_scores(factory, config, run)
    print(f"scores: {run.processed} products, {run.stored} stored, {run.events} events")
    run = JobRun()
    await rankings.update_best_deals(factory, settings.redis_url, run)
    print(f"rankings: {run.processed} products ranked")


async def _seed_history(factory: SessionFactory, days: int, step_hours: int) -> None:
    settings = get_settings()
    registry = build_registry(settings)
    config = await load_scoring_config(factory)
    handles = [h for h in registry.all() if h.provider.is_mock]
    if not handles:
        raise SystemExit("Refusing to seed: no mock providers are active. Seeding never touches real providers.")

    now = utcnow()
    for handle in handles:
        name = handle.provider.name
        async with factory() as session:
            listings = list(await session.scalars(select(ProductPlatform).where(ProductPlatform.platform == name)))
        if not listings:
            raise SystemExit(f"No {name} listings yet. Run `python -m app.cli bootstrap` first.")
        ext_ids = [l.external_product_id for l in listings]
        steps = int(days * 24 / step_hours)
        stored = 0
        for i in range(steps, 0, -1):  # oldest first, so "previous observation" is always earlier
            at = now - timedelta(hours=i * step_hours)
            provider = MockMarketplaceProvider(name, clock=lambda at=at: at)
            run = JobRun()
            async with factory() as session:
                rows = list(await session.scalars(select(ProductPlatform).where(ProductPlatform.id.in_([l.id for l in listings]))))
                await prices.ingest_prices(session, rows, await provider.get_prices(ext_ids), config, run, now=at, detect_events=False)
                await session.commit()
            stored += run.stored
        print(f"{name}: seeded {stored} synthetic observations over {days} days")


async def _score(factory: SessionFactory) -> None:
    """Run the scoring pass once and report how long it took and how much memory it needed."""
    import resource
    import time

    config = await load_scoring_config(factory)
    run, started = JobRun(), time.perf_counter()
    await scoring.calculate_scores(factory, config, run)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux
    print(f"scored {run.processed} products, stored {run.stored} rows, {run.events} events "
          f"in {time.perf_counter() - started:.1f}s (peak memory {peak_mb:.0f} MB)")


async def _make_admin(factory: SessionFactory, email: str) -> None:
    """Grant administrator access to an existing account (there is deliberately no public way to do this)."""
    from sqlalchemy import update

    from app.models import User

    async with factory() as session:
        result = await session.execute(update(User).where(User.email == email.strip().lower()).values(is_admin=True))
        await session.commit()
    if result.rowcount == 0:
        raise SystemExit(f"No account with email {email!r}. Register it on the site first.")
    print(f"{email} is now an administrator")


async def _mcp_check(token: str | None) -> None:
    """Connect to the MCP server exactly as the assistant does and exercise a few tools."""
    from app.services.assistant_clients import open_mcp_backend

    url = get_settings().mcp_server_url
    async with open_mcp_backend(url, token) as backend:
        tools = await backend.tool_definitions()
        print(f"connected to {url}: {len(tools)} tools")
        for name, args in [("get_system_status", {}), ("find_best_deals", {"limit": 1}), ("get_price_alerts", {})]:
            outcome = await backend.call(name, args)
            print(f"  {name}: {'ERROR' if outcome.is_error else 'ok'}  {outcome.text[:110]}")


def _send_test_email(to: str) -> None:
    """Check SMTP settings without involving the database or the queue."""
    from types import SimpleNamespace

    from app.services.channels import EmailChannel

    settings = get_settings()
    if not settings.email_enabled:
        raise SystemExit("SMTP_HOST is not set")
    channel = EmailChannel(settings)
    note = SimpleNamespace(title="AI Deal Hunter SMTP test", message="SMTP settings work.", is_sensitive=True)
    channel._send_sync(channel._build(note, SimpleNamespace(name="", email=to)))  # type: ignore[arg-type]
    print(f"sent to {to} via {settings.smtp_host}:{settings.smtp_port}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap")
    sub.add_parser("score")
    check = sub.add_parser("mcp-check")
    check.add_argument("--token", help="user access token to forward (enables user-scoped tools)")
    sub.add_parser("make-admin").add_argument("email")
    sub.add_parser("vapid-keys", help="print a new VAPID key pair for Web Push")
    test_email = sub.add_parser("send-test-email", help="send one email with the configured SMTP settings")
    test_email.add_argument("to")
    seed = sub.add_parser("seed-history")
    seed.add_argument("--days", type=int, default=60)
    seed.add_argument("--step-hours", type=int, default=3)
    args = parser.parse_args()
    configure_logging("WARNING")

    if args.command == "vapid-keys":
        from app.services.channels import generate_vapid_keys

        public, private = generate_vapid_keys()
        print(f"VAPID_PUBLIC_KEY={public}")
        print(f"VAPID_PRIVATE_KEY={private}")
        return
    if args.command == "send-test-email":
        _send_test_email(args.to)
        return

    async def run() -> None:
        if args.command == "mcp-check":
            await _mcp_check(args.token)
            return
        async with worker_session_factory() as factory:
            if args.command == "bootstrap":
                await _bootstrap(factory)
            elif args.command == "score":
                await _score(factory)
            elif args.command == "make-admin":
                await _make_admin(factory, args.email)
            else:
                await _seed_history(factory, args.days, args.step_hours)

    asyncio.run(run())


if __name__ == "__main__":
    main()
