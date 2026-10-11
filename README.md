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
                         marketdata (provider interface, Dukascopy adapter, candle cache), replay,
                         backtesting (pure order simulator and simulated sessions)
                         ai (Claude coach: read-only tools, bounded tool loop, evidence check)
                         (placeholder packages for Phase 8: billing, broker_adapters)
docker-compose.yml  db, redis, migrate, api, worker, web (nginx serving the SPA and proxying /api); uploads on a shared volume
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

Demo login: `demo@example.com` / `demo-password-1`.

To switch on the AI coach, put your own Anthropic API key in a file named `.env` next to `docker-compose.yml` (`ANTHROPIC_API_KEY=sk-ant-...`) and run `docker compose up -d` again. Without a key the coach page explains how to turn it on, and nothing is sent anywhere. See [docs/ai-coach.md](docs/ai-coach.md). If your network uses a TLS-intercepting proxy, pass its CA to the image builds as a BuildKit secret:

```bash
docker buildx build --load --secret id=extra_ca,src=/path/to/ca.crt -t edgeledger-api backend
docker buildx build --load --secret id=extra_ca,src=/path/to/ca.crt -t edgeledger-web frontend
docker tag edgeledger-api edgeledger-migrate && docker tag edgeledger-api edgeledger-worker
docker compose up -d --no-build
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

The AI coach journey needs a model. To run it without an API key, start the scripted stand-in (`tests/fake_claude.py`, which follows a fixed script and labels its answers as test output) and point the API at it:

```bash
cd backend && python -m tests.fake_claude --port 8765 &
EL_ANTHROPIC_API_KEY=sk-test-fake EL_ANTHROPIC_BASE_URL=http://127.0.0.1:8765 EL_DATABASE_URL=... uvicorn app.main:app --port 8000 &
```

Without it, the journey checks that the coach page explains how to switch the coach on.

### Continuous integration (CircleCI)

`.circleci/config.yml` runs on every pushed commit, on every branch: backend lint, migrations and pytest against real Postgres and Redis; frontend lint, type check, vitest and build; the Playwright journeys; and a Docker job that builds the images, boots the Compose stack and smoke-tests it through nginx. On `main` the Docker job also pushes `edgeledger-api` and `edgeledger-web` to `ghcr.io/<GHCR_USER>/` tagged with the commit SHA and `latest`, once `GHCR_USER` and `GHCR_TOKEN` (a GitHub token with `write:packages`) are set in the CircleCI project's environment variables; until then that step is skipped. After that, a `deploy` job ships `main` to a DigitalOcean Droplet over SSH once `DEPLOY_HOST` and a deploy key are configured (see [docs/deploy-digitalocean.md](docs/deploy-digitalocean.md)); until then it is skipped. The GitHub Actions workflow in `.github/workflows/ci.yml` still runs too.

To turn it on: sign in to circleci.com with GitHub, open Projects, and click Set Up Project next to `kumarzella`, choosing the existing `.circleci/config.yml` on `main`.

### Live Dukascopy check

`python -m scripts.check_dukascopy` (in `backend/`) downloads one real day of EURUSD and USDJPY candles and checks the price scale, field order and bid/ask sides. It needs outbound access to `datafeed.dukascopy.com` and no database.

It passed on 2024-01-16 EURUSD and USDJPY and on 2024-03-05 GBPUSD (2026-10-11). That run used the repo's adapter and decoder with a small stand-in for httpx, because the environment it ran in couldn't reach PyPI. It only passed with longer timeouts and more retries than the old defaults, which led to the throttling handling above.

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
  - Dukascopy throttles bursts with HTTP 429. Requests from one process are spaced 0.5 s apart, and a 429 waits for `Retry-After` (or backs off from 2 s up to 30 s). Other failures back off from 0.5 s. The defaults are a 60 s timeout and 6 retries (`EL_MARKETDATA_TIMEOUT_SECONDS`, `EL_MARKETDATA_RETRIES`, `EL_MARKETDATA_MIN_INTERVAL_SECONDS`). An HTTP 404 means no data for that day.
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

### Phase 6: manual backtesting and deterministic order simulation

- **Sessions** (`/backtest`): a forex pair, a timeframe, a window of up to 31 UTC days that ended before today (the form offers 1 to 10), a starting balance in the pair's quote currency, a commission per 100,000 units per side, and slippage in pips. Bars come from the blind replay engine, so a bar that closes after the cursor is never sent. A session opens with a short warm-up of up to a quarter of the window, and the cursor only moves forward.
- **Orders:** market, limit and stop, sized in units or by a risk amount (turned into units by the server from the stop distance, rounded down to 1,000). An entry can carry a stop-loss and a take-profit, which become reduce-only, one-cancels-the-other orders when it fills. Pending orders can be cancelled and show on the chart as price lines.
- **The simulator** (`app/modules/backtesting/simulator.py`, version `sim-1`) is pure: no database, clock or randomness. It walks 1-minute bid and ask candles, so buys fill on the ask and sells on the bid. When the stop and the target are both reached inside one minute, the stop is assumed to fill first and the fill is marked ambiguous. The full rules are in [docs/backtesting.md](docs/backtesting.md).
- **Positions and results:** fills feed the same position engine and metrics as real trades (average cost, R from the entry's stop). The page shows the open position, open P&L at the bid or ask, orders, fills, simulated trades, and a results panel when the session is finished: net P&L, return, win rate, profit factor, maximum drawdown and an equity curve, with small-sample and ambiguity warnings and a disclaimer.
- **Reproducibility:** the exact configuration is stored on the session. "Re-run and verify" replays the whole order log from the candles and compares every fill with what was stored.
- **Kept apart from real data:** simulated orders, fills and trades live in their own tables (`backtest_*`, migration 0004). They never appear in the journal, dashboard or reports. They are included in the account data export, and screenshots and notes attach to the session.

### Phase 7: AI coach with evidence-grounded tools

- **Coach page** (`/coach`): ask a question about your own trading, or use one of the suggested questions, or summarise a day or a week. Past answers are kept in a history list.
- **Trade page:** an AI review panel reviews the trade against its playbook rules, its notes and similar trades. It suggests up to three tags, and a tag is added only when you click.
- **Every figure comes from the analytics service.** Claude reads your data only through eight read-only, per-user tools (`app/modules/ai/tools.py`), which wrap the same analytics, report, trade and journal code the dashboard uses. Each tool result is an evidence item (E1, E2 and so on), and the answer cites them. Click a citation to see the tool, the filters, the sample size and the exact data.
- **Evidence check** (`app/modules/ai/grounding.py`): every number in an answer must match a tool result at the precision shown. Anything else gets one repair round. If it still doesn't match, the answer is marked "Unverified figures", with the figures listed.
- **Bounded and safe:**
  - At most 6 tool rounds, 16 tool calls and 250,000 tokens per answer, and 30 requests per user per hour.
  - No tool can write or place orders.
  - Notes reach the model only as `untrusted_text` data.
  - Refusals use server-side fallbacks.
- **Stored with evidence:** answers and their evidence are stored in `ai_reviews` and `ai_evidence` (migration 0005), are included in the data export, and can be deleted.
- **Off without a key:** the coach is off until `EL_ANTHROPIC_API_KEY` (or `ANTHROPIC_API_KEY` in Compose's `.env`) is set. Usage is billed to that key. Model `claude-opus-5-5`, effort `medium`.

Details are in [docs/ai-coach.md](docs/ai-coach.md).

## Verification status (2026-10-11)

| Check | How it was run | Result |
|---|---|---|
| Backend pytest: 176 tests covering the AI coach (numerical accuracy against the analytics service, evidence coverage, made-up and uncited figures, cross-user tool access, prompt injection through notes, tool and token budgets, refusals, and the real SDK client against a scripted server), plus auth, authorization, imports, the position engine, instrument rules, the journal, metrics regressions, Dukascopy decoding, the candle cache, MAE/MFE, replay, playbook versions, rule adherence, checklists, annotations, reports, the order simulator's fill rules, and backtest sessions (determinism, re-run verification, ownership and separation from real trades) | Natively, against PostgreSQL 16 and Redis 7 | pass |
| Ruff format and lint; `alembic check` | Natively | clean |
| Frontend vitest (40, including the coach page and the trade review's tag suggestions, the replay state machine, chart states, the adherence panel, chart notes, rules-form validation, the reports page, the order ticket, backtest stepping and results), `tsc -b`, oxlint, `vite build` | Natively, Node 22 | pass |
| Playwright journeys (6 tests, including the AI coach against the scripted server, forex trade chart, MAE/MFE, a review replay, versioned playbook rules with checklist adherence and reports, and a manual backtest with a bracket order, results and a verified re-run) | Natively, API and Vite against the `tradejournal_e2e` database and the generated candle mirror, headless Chromium | pass |
| Live Dukascopy check: real EURUSD, USDJPY and GBPUSD days decoded, ask ≥ bid on every minute | Cloud environment with datafeed.dukascopy.com allowed; httpx replaced by a urllib stand-in (no PyPI there) | pass, after the retry changes |
| Compose stack: all images built; db, redis, migrate, api, worker and web healthy; fixture A imported through nginx on :8080 with dashboard net `260.45`, including a run forced through the Celery worker | Docker. Since 2026-10-11 the stack stores uploads on a shared `storage` volume: MinIO no longer publishes `minio/minio` on Docker Hub, so the image can't be pulled. The 2026-10-11 run also passed the main and playbook browser journeys through :8080 | pass |

The S3 code path (`S3Storage`, enabled with `EL_STORAGE_BACKEND=s3` and the `EL_S3_*` settings) is unit-level only. It has not been exercised against a real S3-compatible store here.

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
- Billing and automated backtesting are placeholder modules with no endpoints.
- The AI coach answers each question on its own (no follow-up memory), doesn't read backtests, and has only been run against a scripted test server here, never against the live Anthropic API, because no key was available. Its evidence check verifies numbers, not reasoning.
- Backtests simulate on 1-minute candles: orders fill whole (no partial fills or depth), the order of events inside a minute is unknown (handled conservatively and marked ambiguous), and fills come from Dukascopy prices, not a broker's. Balances are in the quote currency, with no conversion to an account currency, no swap or financing, and no margin checks.
- Email verification and password reset are not implemented, because no mail service is configured.
- Rule adherence checks what trade data can show. Rules that need chart reading (for example "entered on a break of the range") are covered only by the trader's checklist answers.
- The trades-per-day rule counts trades of the same playbook in the same account on the same session date.

## Next milestone: Phase 8 (broker sync, automated backtesting, billing, deployment hardening and monitoring)

Phase numbers follow the project specification. Phases 1 to 7 are done.

1. Broker API adapters for read-only execution sync, starting with one broker, alongside CSV import.
2. Automated (rule-based) backtests on the same deterministic simulator.
3. Billing and plan limits, including AI coach usage.
4. Production hardening: HTTPS deployment, backups, error monitoring and metrics.

See also [docs/metrics.md](docs/metrics.md), [docs/ai-coach.md](docs/ai-coach.md) and [docs/security-and-compliance.md](docs/security-and-compliance.md).
