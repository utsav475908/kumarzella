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
                         marketdata (provider interface, Dukascopy adapter, candle cache), replay
                         (placeholder packages for Phases 6 to 8: backtesting, ai, billing, broker_adapters)
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

The market-data journey needs candles. Write the generated test candles (synthetic fixtures in Dukascopy's file format, not market history) and start the API against them:

```bash
cd backend && python -m tests.make_mirror /tmp/el-mirror
EL_DUKASCOPY_BASE_URL=file:///tmp/el-mirror EL_DATABASE_URL=postgresql+psycopg://tj:tj@localhost:5432/tradejournal_e2e uvicorn app.main:app --port 8000 &
```

### Live Dukascopy check

`python -m scripts.check_dukascopy` (in `backend/`) downloads one real day of EURUSD and USDJPY candles and checks the price scale, field order and bid/ask sides. It needs outbound access to `datafeed.dukascopy.com` and no database.

The first journey registers a user, then creates an account and imports `fixture_a.csv` through the wizard. It checks the dashboard against the hand-computed expected values, then drills into a losing day. Finally it journals a trade with a note, tags and a playbook.

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
### Phase 3: financial engine and dashboard

- Every metric in [docs/metrics.md](docs/metrics.md) is computed centrally in the analytics module and checked against hand-computed fixtures.
- Dashboard: net P&L and the KPIs, equity curve, daily P&L, P&L by hour, weekday, symbol, tag and playbook, distribution, and a risk-discipline panel. Every chart drills into the filtered trade list.
- Calendar: monthly P&L heat calendar per session date, with day drill-down.
- One shared filter set across the dashboard, trades and calendar, kept in the URL:
  - account, date range, symbol, asset class, playbook, tag
  - direction, session, status, outcome
  - P&L range, entry hour, weekday, text search
- Reports are per currency, and amounts in different currencies are never summed or converted.
- Light and dark themes with colorblind-safe gain and loss colors.
- A synthetic demo dataset that is clearly labelled.

### Phase 4: advanced reports, strategy playbooks and trade annotations

- **Versioned playbooks:**
  - Each playbook holds its setup description, instruments, timeframe, permitted sessions, entry window, written entry, exit, stop, target, sizing and invalidation rules, valid and invalid examples, risk limits, setup screenshots, and pre-trade and post-trade checklists.
  - Rules are never edited in place. Saving creates a new immutable version (`playbook_versions`), and the history is browsable.
  - A trade is pinned to the version that was current when the playbook was assigned (`trades.playbook_version_id`), so new rules never re-judge old trades. Removing and re-assigning the playbook pins the current version.
- **Rule adherence** (`app/modules/analytics/adherence.py`, formulas in [docs/metrics.md](docs/metrics.md#rule-adherence)):
  - Verified rules are checked from trade data and return pass, fail or unknown: instrument, session, entry window, stop recorded, risk within limit, planned reward:risk, trades per day, and loss within planned risk.
  - Checklist items are the trader's own yes/no answers, kept separate from verified rules on screen and in the API.
  - Each trade is followed, broken, incomplete or has no rules. Profit is never part of it.
- **Advanced reports** (`GET /api/v1/analytics/reports`, Reports page): strategy comparison (net, win rate, profit factor, expectancy, average R, average MAE/MFE and followed rate per playbook), rule adherence (outcome groups, per-rule and per-checklist-item results with P&L when failed, and the trades that broke their playbook), P&L by tag, by month and by holding time, and trading costs by symbol. All global filters apply, and rows drill into the journal.
- **Playbook page:** report (dashboard metrics plus adherence for that playbook), rules editor with version history, and screenshots.
- **Trade page:** a playbook-rules panel with the verified checks and checklist toggles, and chart annotations. Click a candle to pin a note, mistake or good decision to it; notes show as chart markers.
- Checklist answers and annotations follow a trade when re-import or an accounting change rebuilds it, and are included in the data export.

### Phase 5: historical market data and trade replay

Built before Phase 4, at the project owner's request, with one provider and one market (Dukascopy, forex).

- **Market data:**
  - A provider-independent interface (`app/modules/marketdata/providers/base.py`).
  - The Dukascopy adapter decodes the datafeed's LZMA "bi5" files of 1-minute bid and ask candles for 28 currency pairs. It checks every record (low ≤ open/close ≤ high, ordered times), so a format change fails loudly instead of producing wrong prices.
  - Retries with backoff. An HTTP 404 means no data for that day.
- **Cache:**
  - Candles are stored per provider, symbol, side and minute (`market_candles`).
  - A coverage row per UTC day (`market_data_coverage`) records complete, error or queued.
  - A day is downloaded once. A failed day is retried after 30 minutes.
  - More than 3 missing days go to the Celery worker; the API answers HTTP 202 and the UI polls.
  - Only completed UTC days are requested.
- **Timeframes and gaps:** 1-minute bars are aggregated on read to 5m, 15m, 30m, 1h or 4h, aligned to UTC. Gap detection reports runs of 5 or more market-open minutes with no ticks.
- **Trade charts:** candlesticks with volume, fills as markers, and planned stop and target lines. Hovering shows OHLC and volume. Instruments the provider doesn't cover fall back to the fills-only chart, with the reason shown.
- **MAE and MFE:**
  - Computed in `app/modules/analytics/excursions.py` from bid bars for longs and ask bars for shorts (see [docs/metrics.md](docs/metrics.md)).
  - Stored on the trade and cleared when its fills change.
  - Shown on the trade, as averages on the dashboard (including R and MFE kept), and can be recomputed in bulk from Settings.
- **Replay:**
  - Saved sessions with a server-side cursor.
  - **Review mode** replays a real trade, with fills appearing as the clock passes them.
  - **Blind mode** reveals bars from the server one step at a time, so a bar that closes after the cursor is never sent, not even a bar that is still forming at a higher timeframe.
  - Play, pause, step, seek, and speeds of 1 to 16 bars per second (at most four requests a second).
  - Progress bar, annotations on any revealed bar, trade notes and playbook overlay, and save and resume.
  - The player is an explicit state machine (`src/lib/replayMachine.ts`) with the states loading, ready, playing, paused, seeking, completed and error.

## Verification status (2026-10-11)

| Check | How it was run | Result |
|---|---|---|
| Backend pytest: 125 tests covering auth, authorization, imports, the position engine, instrument rules, the journal, metrics regressions, Dukascopy decoding, the candle cache, MAE/MFE, replay, playbook versions, rule adherence, checklists, annotations and reports | Natively, against PostgreSQL 16 and Redis 7 | pass |
| Ruff format and lint; `alembic check` | Natively | clean |
| Frontend vitest (32, including the replay state machine, chart states, the adherence panel, chart notes, rules-form validation and the reports page), `tsc -b`, oxlint, `vite build` | Natively, Node 22 | pass |
| Playwright journeys (4 tests, including forex trade chart, MAE/MFE, a review replay, and versioned playbook rules with checklist adherence and reports) | Natively, API and Vite against the `tradejournal_e2e` database and the generated candle mirror, headless Chromium | pass |
| Compose stack: all images built; db, redis, migrate, api, worker and web healthy; fixture A imported through nginx on :8080 with dashboard net `260.45`, including a run forced through the Celery worker | Docker, with MinIO swapped for local storage (MinIO's image was not reachable from the build machine) | pass |

The S3 code path (`S3Storage`) is unit-level only. It has not been exercised against a real MinIO or S3 here.

## Known limitations

- No exchange holiday calendars. Session dates follow the weekday and roll-time rules only.
- Market data covers forex only (Dukascopy). Stocks, futures and options still show the fills-only chart and have no MAE, MFE or replay.
- Dukascopy prices come from Dukascopy's own liquidity, so a broker's fills can sit slightly outside the candles. MAE and MFE use 1-minute bars: minutes that contain a fill are evaluated at the fill prices only, so excursions inside those minutes can be understated. There is no tick-level replay.
- Dukascopy describes its data as for personal use. Each user's charts are fetched for their own trades; displaying the data commercially needs Dukascopy's written permission (see docs/security-and-compliance.md).
- The current UTC day has no candles until Dukascopy publishes it.
- A position that was already open before the first imported execution cannot be detected. Its closing fills would start a new trade, so import complete history.
- Each CSV import targets one account. Multi-account broker files must be split first.
- The UI shows times in the browser's local timezone. Session dates and hour buckets use market time.
- There are no broker API adapters yet; import is CSV only.
- Billing, the AI coach, and both kinds of backtesting are placeholder modules with no endpoints.
- Email verification and password reset are not implemented, because no mail service is configured.
- Rule adherence checks what trade data can show. Rules that need chart reading (for example "entered on a break of the range") are covered only by the trader's checklist answers.
- The trades-per-day rule counts trades of the same playbook in the same account on the same session date.

## Next milestone: Phase 6 (manual backtesting and deterministic order simulation)

Phase numbers follow the project specification. Phases 1 to 5 are done.

1. Backtesting sessions: symbol, timeframe, date range and starting balance, replayed with the blind replay engine so no future bar is ever sent.
2. A deterministic order simulator: market, limit and stop orders, position size, stop-loss and take-profit, commissions and configurable slippage. Ambiguous bars where both stop and target are touched are resolved conservatively or marked ambiguous.
3. Open and closed simulated positions, notes and screenshots, and a results report, all stored apart from real trades with the exact configuration for reproducibility.
4. Determinism tests: the same session and orders always produce the same fills and results.

See also [docs/metrics.md](docs/metrics.md) and [docs/security-and-compliance.md](docs/security-and-compliance.md).
