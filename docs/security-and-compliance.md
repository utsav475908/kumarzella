# Security, privacy and compliance

## Scope

EdgeLedger is a journal and analytics tool:

- It does **not** place, route or modify orders, and it holds no broker trading credentials.
- Future broker adapters will be read-only importers.
- Nothing in the product is investment advice.

## Synthetic data

- Demo data comes from `scripts/seed_demo.py`, uses a fixed seed (42), and belongs to an account flagged `is_demo`. The API returns that flag, and the UI shows a "synthetic demo data" banner.
- Synthetic executions are never presented as real broker fills or as real market history.
- Seeded futures prices are aligned to the tick size so they look plausible, but they do not reproduce any real session.

## Authentication and sessions

- Passwords are hashed with Argon2id (argon2-cffi defaults). Login is rate-limited per IP and email, in Redis, with an in-process fallback.
- Sessions:
  - A session is a random 256-bit token in an HttpOnly, SameSite=Lax cookie (`el_session`).
  - Only its SHA-256 hash is stored, so a database leak does not reveal live sessions.
  - Sessions expire after 7 days by default.
  - Users can list and revoke their sessions.
- CSRF protection is double-submit: the `el_csrf` cookie must match the `X-CSRF-Token` header on every unsafe request.
- Production refuses to start unless `EL_SECRET_KEY` is set to a non-default value and `EL_COOKIE_SECURE=true`, which means HTTPS only.

## Authorization

- Every query is scoped to the authenticated user.
- Child tables carry composite foreign keys, `(account_id, user_id)` → `accounts(id, user_id)`, so the database itself rejects a row that points at another user's account.
- A record that belongs to another user returns 404, not 403, so its existence is not revealed.
- `tests/test_authorization.py` exercises cross-user access on every resource type.

## Data handling

- **Uploads:**
  - CSVs are size-limited (10 MB) and row-limited (200,000).
  - Attachments are checked by magic bytes, not by file extension.
  - Files are stored privately, on local disk or S3 with SSE-AES256, and served only through authenticated endpoints.
- **Logs:**
  - Logs are structured JSON.
  - Passwords, tokens, cookies, CSRF values and authorization headers are redacted.
  - Request bodies and financial payloads are not logged.
- **Audit:** imports, journal edits, manual trades and deletions are written to the audit log with the user, the time, the request ID and the IP.
- **Privacy:**
  - Users can export all their data as JSON (`/api/v1/exports/me`).
  - Deleting an account requires typing its name, and the deletion cascades to that account's trades, executions and journal data.

## Secrets

- All configuration comes from `EL_*` environment variables. `.env` files are git-ignored, and only `.env.example` is committed.
- The credentials in `docker-compose.yml` are for local development only. Replace them in any shared or production environment, and keep real secrets in a secret manager.

## Backups

- Run PostgreSQL in production with point-in-time recovery: base backups plus WAL archiving. Test restores regularly.
- Enable versioning or object lock on the attachment bucket.
- Redis holds only rate-limit counters and the job queue, so it does not need a backup. An import that was queued but never finished can simply be committed again.

## Market data licensing

- EdgeLedger ships with one provider: Dukascopy's public historical datafeed (forex, 1-minute bid/ask candles), published by Dukascopy Bank SA.
- Dukascopy's download tools describe this data as for personal use. We found no public licence for commercial redistribution or display.
- How EdgeLedger uses it:
  - Data is downloaded only when a user opens a chart or replay for their own trades, or starts their own blind replay.
  - Every chart and replay shows the attribution "Historical prices: Dukascopy Bank SA" and the licence note.
  - Candles are cached per deployment and never included in user exports.
- **Before offering EdgeLedger commercially with this data, get written permission from Dukascopy, or switch to a provider whose plan allows display to end users.** The provider interface (`app/modules/marketdata/providers/base.py`) lets another adapter replace Dukascopy without changing charts, MAE/MFE or replay.
- No other market data ships with EdgeLedger. Data from an exchange or a vendor is subject to that provider's licence, which usually covers display limits, redistribution, and the professional or non-professional status of each user.
- Set `EL_MARKETDATA_PROVIDER=none` to turn fetching off entirely.
