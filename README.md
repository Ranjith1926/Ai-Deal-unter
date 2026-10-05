# AI Deal Hunter

Deal intelligence for Amazon India and Flipkart India. Deals are judged against stored price history, not the seller's advertised discount.

Status: **Phase 1 (Foundation)**. See the project specification for the full roadmap.

## Layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI API, config, logging, DB session |
| `frontend/` | Next.js + Tailwind UI |
| `workers/` | Celery app and (later) scheduled jobs |
| `mcp-server/` | Python MCP server for AI shopping tools |
| `database/` | SQL helpers and seed data (migrations arrive in Phase 2, under `backend/`) |
| `infrastructure/` | Dockerfiles |
| `tests/` | Automated tests |

## Run with Docker

```bash
cp .env.example .env        # then set POSTGRES_PASSWORD and update DATABASE_URL to match
docker compose up --build
```

- Frontend: http://localhost:3000
- API: http://localhost:8000/health, `/health/database`, `/health/redis`

## Run locally without Docker

```bash
# Backend (needs Postgres and Redis reachable via .env)
cd backend && python -m venv .venv && .venv/Scripts/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Tests
cd backend && pytest

# Frontend
cd frontend && npm install && npm run dev

# MCP server (stdio)
cd mcp-server && pip install -r requirements.txt && python -m dh_mcp.server
```

## Database migrations

```bash
# Docker
docker compose run --rm backend alembic upgrade head

# Local (DATABASE_URL must point at a running Postgres)
cd backend && alembic upgrade head
alembic upgrade head --sql      # preview SQL without a database
alembic revision --autogenerate -m "describe change"   # after editing models
```

## Background pipeline (Phase 5)

Celery Beat schedules (intervals are environment variables, see `.env.example`):

| Task | Default | What it does |
|---|---|---|
| `pipeline.run` | 30 min | Collect Amazon + Flipkart prices in parallel, then calculate scores, then update rankings |
| `catalog.sync_all` | 6 h | Discover products; normalise, match and upsert listings |
| `alerts.process` | 10 min | Trigger price alerts and queue notifications |
| `notifications.send` | 5 min | Deliver pending notifications (in-app now; email/push/Telegram in Phase 10) |
| `rankings.update` | daily 02:00 UTC | Rebuild the Redis deal rankings |
| `cache.cleanup` | 6 h | Remove cache keys that have no expiry |

On first start the worker syncs the catalogue and runs one pipeline pass automatically.
A failing provider is isolated: its job is logged as failed/partial, the other provider and the
scoring step still run, and its data is flagged stale. Every run is recorded in `provider_sync_logs`
and logged as JSON (job id, provider, start/end, processed/stored/events/errors).

Developer commands (mock providers only):

```bash
docker compose run --rm backend python -m app.cli bootstrap                 # sync + collect + score + rank once
docker compose run --rm backend python -m app.cli seed-history --days 60    # synthetic history for MOCK data
```

`seed-history` refuses to run unless mock providers are active. It never writes data for real providers.

## Tests

```bash
cd backend && pytest                                  # unit tests; integration tests skip without Postgres
docker compose --profile test run --rm backend-tests  # everything, incl. integration tests on a throwaway DB
```

## Website (Phase 7)

Next.js 15 + Tailwind v4, designed with the ui-ux-pro-max skill (design system in
`design-system/ai-deal-hunter/MASTER.md`): emerald trust colour, orange action colour, Rubik + Nunito Sans,
light and dark themes, mobile-first, WCAG 2.2 AA.

- Pages: `/`, `/deals`, `/deals/[id]`, `/search`, `/category/[slug]`, `/compare`, `/alerts`, `/favorites`,
  `/profile`, `/login`, `/register`, `/forgot-password`, `/reset-password`.
- Sign-in uses httpOnly cookies set by a server-side proxy (`/bff/*`); tokens never reach page JavaScript.
  State-changing proxy calls require a same-origin `Origin` header (CSRF defence). Set `COOKIE_SECURE=true` behind HTTPS.
- The site shows a "Demo mode" banner whenever mock marketplace data is active.

Browser tests (needs the stack running; uses real Chromium and axe-core):

```bash
cd tests/e2e && npm install && npm run install-browser && npm test
```

## MCP server (Phase 8)

18 typed tools for AI assistants (`search_products`, `search_deals`, `find_best_deals`, `find_best_value`,
`find_products_under_budget`, `find_price_drops`, `get_product_details`, `get_deal_score`, `get_value_score`,
`get_historical_low`, `get_price_history`, `compare_prices`, `compare_products`, `get_buy_link`,
`create_price_alert`, `get_price_alerts`, `delete_price_alert`, `get_system_status`). The server is a thin client of the
REST API: it has no database access and no scoring logic.

- Inside Docker it runs over streamable HTTP on the private compose network (port 8765, **not** published to the host).
- For a local assistant over stdio: `docker compose run --rm -i mcp-server python -m dh_mcp.server`
  (set `DEAL_HUNTER_EMAIL` / `DEAL_HUNTER_PASSWORD` to enable the alert tools).
- Check the live connection: `docker compose run --rm backend python -m app.cli mcp-check [--token <access token>]`

## AI shopping assistant (Phase 9)

`/assistant` is a chat page backed by `POST /api/assistant/chat`. Claude (`claude-opus-5-5` by default) answers using
only the MCP tools above, so it sees exactly what the website sees. Sign-in is required, requests are rate limited per
user, and actions that change data (create/delete alert) only run when the user's own message asks for them.

Enable it by setting `ANTHROPIC_API_KEY` in `.env` (see `.env.example` for model/effort/limits), then
`docker compose up -d backend`. Without a key the page explains that the assistant is not switched on.

## Admin dashboard (Phase 11)

`/admin` (administrators only): statistics, provider status with enable/disable and manual sync, job logs and failures,
category and product management, and scoring weights/thresholds with validation and a recalculate button. All changes are
audit-logged (`app.audit` logger). There is deliberately no public way to become an administrator; promote an account with:

```bash
docker compose run --rm backend python -m app.cli make-admin you@example.com
```

## Notifications (Phase 10)

Price alerts are delivered on the channels each user picks in **Profile**, and every alert is also kept in the
in-app **Notifications** inbox, so an alert is never lost if an external channel fails.

| Channel | Needs | Notes |
|---|---|---|
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`/`SMTP_PASSWORD`, `EMAIL_FROM` | Development uses the bundled **Mailpit** catcher: open http://localhost:8025 to read every email the app sends. |
| Telegram | `TELEGRAM_BOT_TOKEN` (from @BotFather), optional `TELEGRAM_BOT_USERNAME` | Users message the bot and paste their chat ID in Profile. Sent as plain text. |
| Web Push | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Generate keys with `docker compose run --rm backend python -m app.cli vapid-keys`. Each browser opts in under Profile. |

- A channel without credentials is shown as "Not set up on this server yet" and cannot be selected.
- Delivery runs every 5 minutes (`NOTIFICATION_SEND_MINUTES`), or on demand from **Admin > Jobs > Send notifications**.
  Temporary failures (timeouts, rate limits, 4xx SMTP) are retried up to 3 times; permanent ones fail at once.
- Password-reset links are sent by email. The link is removed from the database as soon as delivery finishes,
  and an undeliverable link is removed after 60 minutes.
- Users can send themselves a test on each channel (10 per hour). Check SMTP settings without the queue:
  `docker compose exec backend python -m app.cli send-test-email you@example.com`.
- Push subscriptions are accepted only for the browser push services (Google, Mozilla, Microsoft, Apple), so a
  user cannot make the server send requests to arbitrary addresses.

## Production hardening (Phase 12)

- **Deploy**: `docker-compose.prod.yml` (Caddy with automatic HTTPS, only ports 80/443 published, non-root read-only containers, healthchecks, resource limits, one-shot migrations, nightly backups). Copy `.env.prod.example` to `.env.prod`, fill in the secrets, then `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`.
- **Safe by default**: with `APP_ENV=production` the API refuses to start on weak secrets, non-HTTPS origins, default DB passwords or mock providers.
- **Abuse protection**: per-user rate limits (client IP forwarded through the proxy chain), login-failure throttling, request-size limits, URL scheme sanitising.
- **Observability**: JSON logs, `/health/{live,ready,providers}`, Prometheus `/metrics` (token-protected) and alert rules in `infrastructure/monitoring/` (`docker-compose.monitoring.yml`).
- **Capacity**: 349 req/s at p95 247 ms with 4 API processes on a 2M-row price history (`tests/load/load_test.py`).
- **Supply chain**: `pip-audit` and `npm audit` are clean; CI (`.github/workflows/ci.yml`) runs tests, build, audits and deployment-file validation, weekly as well as on each push.

Full runbook: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## MCP
`get_system_status` reports API, database and Redis health by calling the backend. Point an MCP client at `python -m dh_mcp.server` (stdio) with `BACKEND_API_URL` set.

## Secrets

Never commit `.env`. Marketplace and affiliate credentials stay server-side; if they are empty, mock providers are used (Phase 3).
