# EdgeLedger

A trading journal and performance-analytics platform. You import broker executions from CSV, and EdgeLedger rebuilds them into trades. You can then journal those trades and measure performance with auditable, decimal-exact metrics.

EdgeLedger is a journal and research tool. **It never places orders or connects to live-money execution.** Demo data is synthetic, and it is always labelled as synthetic in the UI and the API (`is_demo`).

## Architecture

```
frontend/  React 19 + TypeScript + Vite + Tailwind v4 + React Router + TanStack Query + Zod
           Recharts (analytics charts) and lightweight-charts (execution chart)
backend/   FastAPI modular monolith: SQLAlchemy 2 + Alembic + PostgreSQL, Redis, Celery
           app/core      config, db, money (Decimal helpers), security, CSRF, rate limiting, logging, storage
           app/modules   auth, accounts, instruments, imports, executions, positions, trades, journal,
                         playbooks, attachments, audit, analytics
                         (placeholder packages for Phase 4+: marketdata, replay, backtesting, ai, billing, broker_adapters)
docker-compose.yml  db, redis, minio (S3), migrate, api, worker, web (nginx serving the SPA and proxying /api)
```

Rules the code enforces:

- **Money is Decimal end to end.** Columns are `NUMERIC(24,8)` (prices `NUMERIC(24,10)`). The API serializes amounts as strings, and the frontend only formats them.
- **Every financial calculation happens in the backend analytics module.** The frontend never computes a metric. `GET /api/v1/analytics/definitions` and [docs/metrics.md](docs/metrics.md) list each formula.
- **Timestamps are stored in UTC.** Session dates and entry hours are computed in the instrument's market timezone:
  - US equities and options: New York.
  - CME futures: roll at 17:00 Chicago.
  - Forex: rolls at 17:00 New York.
- **Ownership is enforced at every layer:**
  - Every query is scoped to the current user.
  - Composite foreign keys tie child rows to the owning user's account.
  - Tests cover cross-user access on every endpoint.
- **Imports are reproducible:**
  - Every raw CSV row is kept with its validation status.
  - Duplicates are fingerprinted.
  - A commit is one transaction.
  - Trades are rebuilt deterministically (flat to flat, with reversals split and fees allocated pro rata).

## Running it

### Docker Compose (whole stack)

```bash
docker compose up --build
# open http://localhost:8080  (API docs: http://localhost:8080/api/docs)
docker compose exec api python -m scripts.seed_demo     # optional synthetic demo user
```

Demo login: `demo@example.com` / `demo-password-1`. If your network uses a TLS-intercepting proxy, pass its CA to the image builds as a BuildKit secret:

```bash
docker compose build --secret id=extra_ca,src=/path/to/ca.crt
```

### Native development

Prerequisites: Python 3.13, Node 22, PostgreSQL 16 and Redis 7 running locally.

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock
cp .env.example .env                      # adjust EL_DATABASE_URL if needed
createdb tradejournal                     # role/password must match EL_DATABASE_URL
alembic upgrade head
python -m scripts.seed_demo               # optional
uvicorn app.main:app --reload --port 8000

# worker (only when EL_JOBS_EAGER=false; imports over 2000 rows are then queued)
celery -A app.worker worker --loglevel=info

# frontend
cd frontend
npm ci
npm run dev                               # http://localhost:5173, proxies /api to :8000
```

### Tests

```bash
# backend: needs Postgres and Redis; uses database tradejournal_test (set EL_DATABASE_URL to override)
cd backend && pytest -q
ruff format --check app tests alembic && ruff check app tests && alembic check

# frontend unit and component tests, type check, lint, production build
cd frontend && npm test && npm run typecheck && npm run lint && npm run build
```

### End-to-end tests

Playwright runs against a stack that is already running: the API on :8000 and Vite on :5173. Point the API at a throwaway database:

```bash
createdb tradejournal_e2e
cd backend && EL_DATABASE_URL=postgresql+psycopg://tj:tj@localhost:5432/tradejournal_e2e alembic upgrade head
EL_DATABASE_URL=postgresql+psycopg://tj:tj@localhost:5432/tradejournal_e2e uvicorn app.main:app --port 8000 &
cd ../frontend && npm run dev &
npx playwright test          # PW_CHROMIUM=/path/to/chromium to use a preinstalled browser
```

The journey registers a user, then creates an account and imports `fixture_a.csv` through the wizard. It checks the dashboard against the hand-computed expected values, then drills into a losing day. Finally it journals a trade with a note, tags and a playbook.

## What is implemented

### Phase 1: foundation

- Auth: registration, login and logout; Argon2 password hashing; server-side sessions stored as hashed tokens in HttpOnly SameSite cookies; a list of active sessions you can revoke.
- Request protection: double-submit CSRF, rate limiting in Redis (with a local fallback), structured JSON logs with secret redaction, and request IDs.
- Errors use one envelope: `{"error": {code, message, details}}`. Health checks are at `/healthz` and `/readyz`, and readiness checks the database and Redis.
- Accounts:
  - CRUD with currency, broker, starting balance, and risk limits (max risk per trade, daily loss limit).
  - Cash transactions.
  - Deletion requires typing the account name.
  - Full personal data export at `/api/v1/exports/me`.
- Instrument rules:
  - Stocks.
  - Futures, with multipliers by root symbol.
  - OCC-format options.
  - Forex, with P&L in the quote currency.
  - Crypto.
- Audit log of journal edits, imports and deletions.

### Phase 2: import and the trade journal

- CSV import wizard with five steps: upload, column mapping (with presets and auto-suggestion), preview of valid, rejected and duplicate rows with reasons, transactional commit, and import history.
- Position engine:
  - Rebuilds trades flat to flat.
  - Handles scale-ins, scale-outs and reversals.
  - Supports average-cost or FIFO for partial realized P&L.
  - Allocates fees.
  - Re-importing overlapping files is idempotent.
- Trade journal:
  - Filterable and sortable trade list.
  - Trade detail with every execution and its source CSV row.
  - Planned stop and target, initial risk, R-multiple, and a plain-language calculation breakdown.
  - Notes, tags, playbook assignment, day notes, and image attachments (sniffed by type and stored privately on local disk or S3).
  - Manual trades.
  - Previous and next navigation.
- Dashboard: net P&L and all the KPIs in docs/metrics.md, equity curve, daily P&L, P&L by hour, weekday, symbol, tag and playbook, distribution, and a risk-discipline panel. Every chart drills into the filtered trade list.
- Calendar: monthly P&L heat calendar per session date, with day drill-down.
- One shared filter set across the dashboard, trades and calendar, kept in the URL:
  - account, date range, symbol, asset class, playbook, tag
  - direction, session, status, outcome
  - P&L range, entry hour, weekday, text search

### Phase 3: playbooks and reporting

- Playbooks with rules, criteria and checklists, and per-playbook performance reports. Trades with no playbook appear as "No playbook".
- Reports are per currency, and amounts in different currencies are never summed or converted.
- Light and dark themes with colorblind-safe gain and loss colors.
- A synthetic demo dataset that is clearly labelled.

## Verification status (2026-10-10)

| Check | How it was run | Result |
|---|---|---|
| Backend pytest: 77 tests covering auth, authorization, imports, the position engine, instrument rules, the journal and metrics regressions | Natively, against PostgreSQL 16 and Redis 7 | pass |
| Ruff format and lint; `alembic check` | Natively | clean |
| Frontend vitest (15), `tsc -b`, oxlint, `vite build` | Natively, Node 22 | pass |
| Playwright journey (2 tests) | Natively, API and Vite against the `tradejournal_e2e` database, headless Chromium | pass |
| Compose stack: all images built; db, redis, migrate, api, worker and web healthy; fixture A imported through nginx on :8080 with dashboard net `260.45`, including a run forced through the Celery worker | Docker, with MinIO swapped for local storage (MinIO's image was not reachable from the build machine) | pass |

The S3 code path (`S3Storage`) is unit-level only. It has not been exercised against a real MinIO or S3 here.

## Known limitations

- No exchange holiday calendars. Session dates follow the weekday and roll-time rules only.
- MAE and MFE, the replay, and price charts beyond the plotted fills all need historical market data, which arrives in Phase 4.
- A position that was already open before the first imported execution cannot be detected. Its closing fills would start a new trade, so import complete history.
- Each CSV import targets one account. Multi-account broker files must be split first.
- The UI shows times in the browser's local timezone. Session dates and hour buckets use market time.
- There are no broker API adapters yet; import is CSV only.
- Billing, the AI coach, and both kinds of backtesting are placeholder modules with no endpoints.
- Email verification and password reset are not implemented, because no mail service is configured.

## Next milestone: Phase 4

1. Market-data module: a provider interface, licensed historical OHLCV ingestion with a cached bar store, and a clear statement of licensing and attribution for each provider.
2. Candlestick trade charts with fills overlaid, plus MAE and MFE, and best exit, computed in analytics.
3. Trade replay: step through bars around a trade with the journal alongside.
4. Exchange holiday calendars for session dates.
5. Broker adapter interface. The first adapter is read-only and imports executions; it never places orders.

See also [docs/metrics.md](docs/metrics.md) and [docs/security-and-compliance.md](docs/security-and-compliance.md).
