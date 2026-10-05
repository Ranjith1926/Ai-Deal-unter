# Deployment and Operations Guide

## 1. Overview

This guide covers running AI Deal Hunter in production with `docker-compose.prod.yml`: configuration, first deployment, upgrades, backups and restores, monitoring, scaling, and troubleshooting.

Topology:

| Service | Role | Exposed |
|---|---|---|
| `caddy` | TLS termination (automatic Let's Encrypt), HSTS, compression, request-size limit | **80, 443 (only service published)** |
| `frontend` | Next.js app and server-side BFF (holds session cookies, proxies to the API) | private |
| `backend` | FastAPI API, `WEB_CONCURRENCY` worker processes | private |
| `celery-worker`, `celery-beat` | Scheduled collection, scoring, alerts | private |
| `mcp-server` | MCP tools over streamable HTTP for the assistant | private |
| `postgres`, `redis` | Data stores | private |
| `migrate` | One-shot Alembic upgrade before the API and workers start | – |
| `backup` | Nightly `pg_dump` into the `backups` volume | – |

The browser only ever talks to Caddy and the Next.js app. `/metrics`, `/health/*` and API docs are blocked at the proxy and are reachable only on the private network.

## 2. Requirements

1. A Linux host with Docker Engine 25+ and the Compose plugin, at least 2 vCPU and 4 GB RAM.
2. A DNS record for the site domain pointing at the host, with ports 80 and 443 reachable (needed for certificate issuance).
3. Real marketplace affiliate credentials for any provider you want live data from (see section 9).

## 3. First deployment

1. Copy the template and fill in every `CHANGE_ME`:
   ```
   cp .env.prod.example .env.prod
   openssl rand -hex 32   # JWT_SECRET
   openssl rand -hex 32   # METRICS_TOKEN
   openssl rand -hex 24   # POSTGRES_PASSWORD (also put it inside DATABASE_URL)
   ```
2. Set `SITE_ADDRESS`, `CORS_ORIGINS` and `FRONTEND_URL` to your `https://` domain.
3. Start the stack:
   ```
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
   ```
4. Create the first administrator (register in the UI first, then promote):
   ```
   docker compose -f docker-compose.prod.yml exec backend python -m app.cli make-admin you@example.com
   ```

`.env.prod` is git-ignored. Never commit it, and keep it readable by the deploy user only (`chmod 600`).

### Startup safety checks

With `APP_ENV=production` the API **refuses to start** (and logs every reason) if any of these hold: `JWT_SECRET` shorter than 32 characters or placeholder-like; a default database password; `CORS_ORIGINS` or `FRONTEND_URL` not `https://` (or a wildcard); `USE_MOCK_PROVIDERS=true`; `METRICS_TOKEN` shorter than 24 characters. API docs are disabled, and `/metrics` returns 404 unless `METRICS_TOKEN` is set.

## 4. Configuration reference (production-relevant)

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` enables the safety checks above, HSTS and hides docs |
| `COOKIE_SECURE` | – | Must be `true` behind HTTPS so session cookies are `Secure` |
| `TRUSTED_PROXY_COUNT` | `0` | Reverse proxies appending to `X-Forwarded-For`. The bundled stack needs `1`. A wrong value lets clients spoof their IP and bypass rate limits |
| `METRICS_TOKEN` | – | Bearer token for `/metrics` |
| `WEB_CONCURRENCY` | `4` (prod file) | API worker processes |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | `5`, `5` | Per-process pool. Keep `WEB_CONCURRENCY × (pool + overflow)` well under Postgres `max_connections` (100) |
| `MAX_REQUEST_BODY_BYTES` | `1000000` | API request body cap (Caddy caps at 2 MB first) |
| `LOGIN_FAILURE_LIMIT`, `LOGIN_FAILURE_WINDOW_SECONDS` | `5`, `900` | Failed sign-ins per account+IP before a temporary lock |
| `CELERY_CONCURRENCY` | `2` | Parallel background jobs |
| `BACKUP_KEEP_DAYS`, `BACKUP_INTERVAL_SECONDS` | `14`, `86400` | Backup retention and cadence |
| `HTTP_PORT`, `HTTPS_PORT` | `80`, `443` | Host ports for Caddy. Change only for local trials |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` | –, `587`, `starttls` | Email delivery (alerts and password resets). Without `SMTP_HOST`, password reset cannot work |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | – | Telegram alerts |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | – | Web Push alerts (`python -m app.cli vapid-keys`) |
| `NOTIFICATION_MAX_ATTEMPTS`, `SENSITIVE_MESSAGE_TTL_MINUTES` | `3`, `60` | Retries for temporary failures; lifetime of an undelivered reset link |

## 5. Container hardening applied

Every service uses `no-new-privileges` and `cap_drop: ALL`; application containers run as a non-root user with a read-only root filesystem (writable `tmpfs` only for `/tmp`); memory and CPU limits are set; logs rotate at 10 MB × 5 files; restart policy is `unless-stopped`. Healthchecks: API `/health/live`, frontend `/healthz`, Postgres `pg_isready`, Redis `ping`, Celery worker `inspect ping`. Dependencies wait for healthy upstreams, and the API and workers wait for `migrate` to complete.

Redis runs with AOF persistence and `noeviction`, so queued jobs are not silently dropped under memory pressure.

## 6. Upgrades

1. Take a backup first (section 7).
2. `git pull`, then `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`.
3. The `migrate` service applies Alembic migrations before the new API starts. If it fails, the API stays on the old version; read its logs with `docker compose ... logs migrate`.
4. Confirm `docker compose ... ps` shows every service healthy.

Rolling back code is safe only if the migration was backward compatible. Otherwise restore the pre-upgrade backup (section 7).

## 7. Backups and restore

The `backup` service writes compressed custom-format dumps to the `backups` volume, verifies each by listing its contents, and prunes by age.

- On demand: `docker compose -f docker-compose.prod.yml run --rm backup once`
- **Copy dumps off the host** (object storage or another machine). A backup on the same disk as the database does not survive a disk failure. This is not automated here.
- **Restore drill** (non-destructive; creates and drops a scratch database, compares row counts with the live one):
  ```
  docker compose -f docker-compose.prod.yml run --rm --entrypoint sh \
    -v ./infrastructure/backup/restore-check.sh:/restore-check.sh:ro backup \
    -c 'sh /restore-check.sh $(ls -t /backups/*.dump | head -1)'
  ```
  Run it after setting up and then periodically; an untested backup is not a backup.
- **Disaster restore**: stop `backend`, `celery-worker`, `celery-beat`; create an empty database; `pg_restore --no-owner -d <db> <dump>`; start the services.

## 8. Monitoring

`docker-compose.monitoring.yml` adds Prometheus (bound to `127.0.0.1:9090`, view through an SSH tunnel) with the rules in `infrastructure/monitoring/alerts.yml`:

| Alert | Fires when |
|---|---|
| `ApiDown` | Scrapes fail for 2 min |
| `HighServerErrorRate` | 5xx rate above 2% for 5 min |
| `SlowRequests` | p95 latency above 750 ms for 10 min |
| `RequestBacklog` | More than 80 requests in flight for 5 min |
| `ProviderStale` | An enabled provider has had no successful sync for 2 h |
| `ProviderJobsFailing` | More than 10 failed jobs in 24 h |
| `CatalogueEmpty`, `NoDealEventsDetected` | Data pipeline stopped producing |

Write the token to `infrastructure/monitoring/metrics_token` (git-ignored). Alert *routing* (email, Slack, pager) needs an Alertmanager or Grafana setup that this repository does not include.

Other signals: structured JSON logs with correlation IDs, `/health/ready` (503 when Postgres or Redis is down), and `/health/providers` (per-provider state: healthy, stale, failing, disabled, unavailable).

## 9. Marketplace data

Production never serves mock data. Without credentials a provider reports `unavailable` and the catalogue stays empty. Amazon requires approved Associates/PA-API access and Flipkart requires an approved affiliate account. Do not scrape marketplace pages as a substitute; it breaches their terms.

## 10. Capacity and load-test results

Measured on a developer workstation (16 logical CPUs shared by the API, Postgres and the load generator) against a scratch database with **2 million price rows**, 40 concurrent clients, 30 s, realistic endpoint mix (`tests/load/load_test.py`):

| API processes | Throughput | p50 | p95 | p99 | Errors | Postgres connections |
|---|---|---|---|---|---|---|
| 1 | 135 req/s | 282 ms | 405 ms | 507 ms | 0% | – |
| 4 | **349 req/s** | 101 ms | 247 ms | 323 ms | 0% | 20 |

Unloaded, every endpoint answers in 2–30 ms at p95. Scaling is roughly linear in processes until Postgres or CPU saturates. Treat these as relative figures: run `tests/load/load_test.py` against your own hardware before sizing a launch. Score calculation holds about 245 MB at peak for this dataset (batched), so the worker memory limit of 1 GB has headroom.

Server-rendered public pages are cached for 60 s per URL, so their request volume to the API is bounded. Authenticated and `/bff` traffic carries the end user's address (`X-Forwarded-For`), so rate limits and login throttling apply per user, not per server.

## 11. Security checklist

1. `APP_ENV=production`, `COOKIE_SECURE=true`, `TRUSTED_PROXY_COUNT=1`.
2. Strong random `JWT_SECRET`, `METRICS_TOKEN`, database password; none committed.
3. Only ports 80/443 open on the host firewall; Postgres, Redis and the API are never published.
4. Dependency audits clean (`pip-audit`, `npm audit --omit=dev`), enforced weekly and on every push in CI.
5. Off-host backups and a tested restore.
6. SMTP uses `starttls` or `ssl` (the API refuses to start in production otherwise). Password-reset links are scrubbed from the database once delivery finishes, or after 60 minutes if they cannot be delivered.

## 12. Troubleshooting

| Symptom | Check |
|---|---|
| API restarts immediately | `logs backend`: the "Refusing to start" line lists every configuration problem |
| Site shows certificate error | DNS must resolve to this host and ports 80/443 must be open; see `logs caddy` |
| Everyone gets 429 | `TRUSTED_PROXY_COUNT` is 0 behind a proxy, so all users share one IP |
| Users locked out after typos | Expected after 5 failures per account+IP in 15 min; wait or delete the `dh:lf:*` keys in Redis |
| Prices look stale | `/health/providers`, then the Admin → Jobs page and `logs celery-worker` |
| Migration failed during upgrade | `logs migrate`; restore the pre-upgrade backup if needed |
