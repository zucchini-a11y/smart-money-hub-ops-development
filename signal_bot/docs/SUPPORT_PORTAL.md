# VAYDA staff support portal

The Support Portal is a separate staff-only web app for reviewing Telegram
support requests, replying privately as the named responder, and managing
employee accounts. It uses the bot's PostgreSQL `smh` schema. No portal
accounts are provisioned automatically.

## What is included

- Admin-created staff accounts only; there is no public registration.
- The first administrator is provisioned from the command line. Administrators
  can then create or deactivate employee accounts in the portal.
- A new employee receives a one-time temporary password and must change it
  before accessing cases. Do not send the password through Telegram.
- Replies are recorded in an outbox before the Python bot sends them. The
  message identifies the responder as `VAYDA | <display name>`.
- A repeated request with the same idempotency key returns the existing reply.
- A Telegram timeout is marked **uncertain** and is not retried automatically.
  Verify with the member before taking any further action.
- Deactivating an employee ends their sessions and cancels replies still queued.
- Sessions use hashed random tokens in PostgreSQL and an HttpOnly, SameSite
  cookie. Production cookies require HTTPS. Passwords use scrypt hashes.

## Requirements and environment

The portal has no dependency on Replit Agent or Replit-managed authentication.
It needs:

- Node.js 24 (or a compatible version supporting the project TypeScript output)
  for the API and static frontend.
- Python 3.12 for the bot and database administration commands.
- PostgreSQL for shared production records.
- HTTPS for staff logins and secure session cookies.
- A reverse proxy or hosting setup that serves the web app and forwards `/api`
  to the Node API on the same origin.
- The existing Telegram bot process, which runs the reply outbox worker.

Required server environment:

| Variable | Purpose |
|---|---|
| `SMH_DATABASE_URL` | Preferred PostgreSQL connection string for the bot and the production API. Use the same database/schema for both. |
| `DATABASE_URL` | Fallback database connection string. The API uses this in development; in production it is used only if `SMH_DATABASE_URL` is absent. |
| `NODE_ENV=production` | Makes the API prefer `SMH_DATABASE_URL` and enables secure cookies. |
| `PORT` | HTTP port supplied by the hosting provider for the API. |
| `TELEGRAM_BOT_TOKEN` | Required by the Python bot to deliver staff replies. Store only in the host's secret manager. |
| `ADMIN_TELEGRAM_ID` | Existing bot administrator configuration. |
| `PRO_SIGNALS_CHANNEL_ID`, `MARKET_ANALYSIS_CHANNEL_ID` | Existing bot destination configuration; portal replies do not publish to either channel. |
| `SMH_ALLOW_PUBLISHING` | Existing bot publishing lock. The support portal does not change it. |

Do not point a development API or isolated bot at the production database. The
test bot must continue using its separate test token, channels, and database.

## Shared Replit Development Support Portal

The Signal bot can optionally submit test-bot support requests to the shared
Operations Center portal. This bridge is disabled by default and refuses to
start if enabled outside an isolated bot using the `smh_test` schema. It does
not replace the existing local support behavior when disabled.

For a Development-only test:

1. Keep `SMH_ISOLATED_TEST_INSTANCE=true`, use a dedicated test Telegram bot,
   and confirm the bot database schema is `smh_test`.
2. Set `SMH_SUPPORT_API_ENABLED=true` and `SMH_SUPPORT_API_URL` to the
   Development API origin. Local Replit workflows may use
   `http://127.0.0.1:8080`; remote hosts require HTTPS.
3. Store the same random bearer token as `SMH_SUPPORT_SIGNALS_TOKEN` in the
   Replit Development API and isolated bot secret managers. Never put it in
   `.env.example`, source code, or chat.
4. Run tests before starting the isolated test bot. This integration does not
   start a bot, change publishing permissions, or route production cases.

When enabled, member contact messages go to the shared portal. Staff replies
are delivered by the Signal bot through the API outbox. Telegram delivery
timeouts are marked uncertain and are never automatically retried. If the API
cannot accept a member message, the bot says it was not submitted and does not
silently save it in the separate local queue.

## Database migration and first administrator

Do not run this on the current production database as part of code development.
Before a planned rollout:

### Replit Development setup

For the Replit **Development** database only, after migration 004 is applied,
run this short command from the project's Development Shell:

```sh
python -m smh.portal_admin setup-dev
```

The command uses `DATABASE_URL` only, refuses a Production process or isolated
test-bot process, and asks you to type `DEVELOPMENT` before writing. It then
prompts for the administrator email and display name and asks for a password
twice without displaying it. It creates only the first portal administrator.
If the Shell cannot hide password input, it stops before writing anything. Do
not run it while the Database pane is set to Production.

### Standard-host rollout

1. Take a database backup and chart/image export, then test restoration on a
   separate database.
2. Plan a maintenance window. The updated bot requires schema version 4; do
   not restart an old bot against a database after applying the new migration.
3. Set `SMH_DATABASE_URL` for the intended PostgreSQL database and apply the
   migration on a standard external host:

   ```sh
   python -m smh.admin_cli migrate --external-or-development
   ```

   This command applies the numbered SQL migrations, including
   `004_support_portal.sql`. The explicit flag confirms the target is an
   external or development database; do not use it against a Replit-managed
   production database.
4. Bootstrap the first portal administrator once:

   ```sh
   python -m smh.portal_admin create-admin \
     --email admin@example.com \
     --display-name "Portal Administrator" \
     --confirm-database-target
   ```

   The command creates and prints a temporary password once. Run it in a
   private terminal, deliver the temporary password through a secure channel,
   sign in over HTTPS, and change it immediately. The command refuses to
   create a second bootstrap account. If the only admin is locked out, use
   `reset-admin` for that existing email instead of creating a new account.
5. Build and run the updated API, static web app, and Python bot using the
   deployment instructions for the selected host. Keep one bot process per
   bot token/database. The bot worker is part of `python main.py`; no separate
   scheduled job is needed.
6. Test staff login, forced password change, case access, employee create/
   deactivate, reply success, and uncertain-send handling in a private test
   environment before opening staff access in production.

## Running on a standard host

Build the two Node packages. Vite requires `PORT` and `BASE_PATH` even during a
static build; use the path where the portal will be mounted:

```sh
pnpm --filter @workspace/api-server run build
PORT=5000 BASE_PATH=/ pnpm --filter @workspace/support-portal run build
```

Run the Node API as a persistent service with `NODE_ENV=production` and the
provider-supplied `PORT`. Serve the support portal build as a static web site
on the same HTTPS origin and forward `/api/*` to the API service. Run the bot
as a separate persistent Python service:

```sh
python main.py
```

Install Python dependencies from the pinned `pyproject.toml`/`requirements.txt`
and Node packages from the lockfile. Store Telegram tokens and PostgreSQL URLs
in the hosting provider's secret manager. The bot's graceful-shutdown and
database recovery behavior remains in the Python process. Off-host database
backups and chart exports remain the operator's responsibility; this portal
does not automate backups.

## Export, restore, and staff account handling

The existing portable bundle now includes support cases, replies, audit
records, and staff account records so support history can be migrated. It
does **not** include active portal sessions; restoration therefore signs
everyone out. A reply interrupted while sending is restored as uncertain and
is never replayed. Keep exports encrypted and access-controlled: they contain
member support text and password hashes.

Use the existing backup/export and restore procedures in
[`PORTABILITY.md`](PORTABILITY.md). Restore only into an empty, migrated
database while the bot is stopped. After restoration, confirm staff accounts
and permissions, then test login and reply delivery in the intended private
environment.

## Current verification boundary

Offline type checks and mocked Python delivery tests do not prove staff login
or Telegram delivery on a live account. No portal staff account was created,
no real Telegram reply was sent, no production database was migrated, and no
production bot setting was changed during implementation.
