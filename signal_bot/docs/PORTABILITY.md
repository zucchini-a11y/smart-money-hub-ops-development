# VAYDA SMART MONEY HUB — portable operations

This document supersedes the original SQLite-only hosting instructions in README.

The release verification commands are:
```
python tools/package_source.py
python tools/verify_release.py generated-artifacts/vayda-smart-money-hub-source.zip --safe-startup
```
The verifier installs pinned requirements in a temporary directory, validates the ZIP
manifest, runs the complete test suite, and optionally runs
`python -m smh.check_config --safe-startup`. That startup check uses read-only database
transactions and Telegram identity/channel-permission API calls. It never starts an
Updater, polls for updates, sends messages, applies migrations, or changes publishing
settings. The old `--live-locked-start` flag remains as a compatibility alias; it no
longer starts the bot.

## Runtime dependencies and cost

Use a standard Linux Python 3.12+ host, requirements.txt, outbound HTTPS to api.telegram.org, and PostgreSQL
14+ with direct/session-mode connections (not transaction-pooling mode: the worker
uses a session advisory lock). No Replit SDK, AI Agent, Replit authentication,
Replit storage API, or AI service is needed at runtime.

The default DATABASE_URL in Replit points to its managed PostgreSQL. Outside Replit,
set SMH_DATABASE_URL to any managed PostgreSQL provider. Use TLS (`sslmode=require`,
or preferably `verify-full` with the provider CA). Hosting and PostgreSQL/storage,
backup retention, and egress may be paid. Replace these with your own provider before
losing access to a subscription. Telegram Bot API and the Python libraries do not
require paid AI/market-data subscriptions.

Charts are stored as PostgreSQL BYTEA records, including original bytes and annotated
copies. Drafts/publication records reference content-addressed IDs. Local image files
are disposable cache. A new host can reconstruct them from PostgreSQL. This simplifies
portability but uses database storage; budget for image volume and backup size.

## Clean setup on a standard Python host

1. Download and extract the source archive. Install Python 3.12+.
2. `python -m pip install -r requirements.txt`
3. Supply environment variables using the host's secure secret manager. `.env.example`
   contains placeholders, **not usable credentials**. The application does not load
   `.env` automatically. Never check an actual `.env` into source control.
4. Create an empty PostgreSQL database. Set `SMH_DATABASE_URL` securely.
5. For an external PostgreSQL provider or development database only:
   `python -m smh.admin_cli migrate --external-or-development`
   Migration SQL is in `migrations/001_postgresql.sql`,
   `migrations/002_member_requests.sql`,
   `migrations/003_assistant_escalations.sql`, and
   `migrations/004_support_portal.sql`; rerunning is safe. Schema version 4 adds
   independent destination applications, PRO verification state, private evidence
   references, member-request audit events, assistant support cases, staff accounts,
   session records, reply outbox, and portal audit history. Runtime does not create
   PostgreSQL tables.
   Apply every numbered migration before starting a new host.
   **Replit-managed production:** use Replit Publish's schema-diff process instead.
   The schema-version default is part of the DDL, so a fresh schema-only deployment
   does not need startup DDL or migration-metadata inserts.
6. Set all four Telegram variables described below and `SMH_ALLOW_PUBLISHING=false`.
7. `python -m smh.admin_cli health`; `python -m smh.check_config`
8. `python main.py`. Verify the startup message reports administrator/channel verification
   successful. The configured user must be an administrator of BOTH channels; the bot
   needs Post Messages, Edit Messages, and Invite Users. The user must first open a
   private chat with the bot. Destination IDs must resolve to two distinct channels.
9. Leave publishing disabled until you approve the restored data and channel mapping.
   Enabling requires `SMH_ALLOW_PUBLISHING=true` and a restart. Every send checks live
   channel/admin permissions again. This build has NOT enabled that switch.

## Environment variables

Required: `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `PRO_SIGNALS_CHANNEL_ID`,
`MARKET_ANALYSIS_CHANNEL_ID`, and `SMH_DATABASE_URL` (or `DATABASE_URL` fallback).
All credentials belong in a secret manager.

Optional: `SMH_DATA_DIR` (cache/log/temporary backup directory, default data),
`SMH_BACKUP_RETENTION` (local backup count, default 14), `SMH_ALLOW_PUBLISHING`
(default false). `SMH_TEST_MODE=1` permits SQLite configuration for isolated tests
only, never production. `SMH_TEST_POSTGRES_URL` can direct integration tests to a
disposable development database. Tests create/drop only randomized `test_*` schemas.
Never point tests at production.

For owner-managed educational video posts, configure `SMH_EDUCATION_VIDEO_GROUP_ID`
and `SMH_EDUCATION_VIDEO_TOPIC_ID` independently from the member-access group, plus
`SMH_EDUCATION_VIDEO_STORAGE_DIR`. The bot worker and portal API must see the same
database schema and shared persistent video directory. For isolated tests use the
`SMH_TEST_EDUCATION_VIDEO_GROUP_ID`, `SMH_TEST_EDUCATION_VIDEO_TOPIC_ID`, and
`SMH_TEST_EDUCATION_VIDEO_STORAGE_DIR` variables with a private test forum. The video
destination is never inferred from the member-access link. Topic name defaults to
`Video tutorials`; use the optional matching `*_EDUCATION_VIDEO_TOPIC_NAME` value to
change its display label. The Bot API file limit is enforced at 50 MB.

`EXNESS_PARTNER_LINK` configures the PRO registration button. For the isolated test
bot, use `SMH_TEST_EXNESS_PARTNER_LINK`; the test configuration never falls back to
the production link. There is no Exness API or automatic account verification: the
administrator must review registration and funding evidence manually. The bot stores
only a Telegram file reference for submitted evidence and does not OCR or infer account
status from the image.

## Export, backup and restore

Commands are standard Python; no provider SDK:

```
python -m smh.admin_cli export --file /secure-backups/vayda.zip
python -m smh.admin_cli restore --file /secure-backups/vayda.zip
```

Export takes a consistent database transaction under the same advisory transaction
lock used by application writes. It includes settings, offset, trades, events, drafts,
applications, independent destination requests, their audit events, access, buttons,
operations, receipts, assistant support history, staff account records, private
evidence file references, and all chart bytes.
The ZIP contains `database.json`, `images/*`, and `manifest.json` with checksums and
links to draft owners/analysis operations/trade IDs. Format 5 also includes
`videos/*` and their database-record references/checksums. Never share this private
export as though it were the source archive. Encrypt it at rest and in transit.

Restore validates checksums, expected tables/columns, and image digests, and inserts
transactionally into an **empty target only**. Existing records are never overwritten.
Active portal sessions are omitted so restoration signs staff out. It marks interrupted
signal operations and support replies uncertain and invalidates old buttons.
Receipt recovery reconciles successful sends without sending again.

For native PostgreSQL disaster recovery, also enable your provider's managed automated
backups/PITR and perform periodic restore drills into a separate database. `pg_dump`
and `pg_restore` are optional standard PostgreSQL tools, not runtime dependencies.
The application export is portable across SQLite testing and PostgreSQL; native dumps
are PostgreSQL-only. Neither local ZIPs nor local logs survive an ephemeral host loss.
Schedule encrypted off-host exports yourself or use managed backup/PITR; automated
upload to a second provider is not included.

## Migrating hosts without duplicate messages

1. Set publishing false. Stop the old worker completely, including its automatic
   restart/scheduler. Only one host may poll this token.
2. Export AFTER shutdown. Keep the old database and export until recovery is confirmed.
3. Create the destination database and apply migrations; restore the export.
4. Supply the SAME bot identity, administrator, and channel IDs. No credentials travel
   in the source archive. Copy them through the new host's secret manager.
5. Start exactly one worker with publishing false. Chart cache regenerates automatically.
6. Inspect history, recovered drafts, operations and Telegram channel posts.
   A send that timed out is ambiguous: inspect the channel and reconcile its exact
   message ID, never automatically resend it. Old backups may miss recent messages;
   no software can promise zero data loss from an outdated recovery point. Use a final
   stopped-worker export and PITR where available.
7. Enable publishing only after identity/channel verification and operator review.

SQLite legacy import (old worker must be stopped):
`python -m smh.admin_cli import-sqlite --sqlite-dir data --file /secure-backups/legacy.zip`
It converts local image paths to persistent references, imports receipts, and restores
into an empty PostgreSQL target. Preserve a separate untouched source backup first.

## Workers, monitoring, shutdown

One `python main.py` worker. No web UI, Redis, Celery, or extra worker is required.
Within that process: Telegram long polling, a 60-second health monitor, a 20-second
watchdog, and daily backup creation. SIGTERM/SIGINT trigger graceful shutdown; allow
at least 60 seconds before forced kill. Use a standard host process supervisor with
restart-on-failure and secure environment injection.

`/health` is administrator-only; `python -m smh.admin_cli health` is a database probe.
Monitor process uptime externally as well. A database connection failure cannot
silently reconnect and steal the advisory lock; supervisor/operator restart is needed.
Two hosts using different databases cannot share the same lock: stopping the old host
is mandatory. Telegram polling conflicts are a further safeguard, not distributed
exactly-once delivery.

## Test commands and limits

`python -m unittest discover -s tests -v`

With a PostgreSQL test URL, tests exercise real PostgreSQL, SQLite, permission/routing
gates, uncertain sends, receipt recovery, complete export/restore, chart reconstruction,
and post-restore no-replay behavior. Telegram send calls in tests are mocked.
Without a test PostgreSQL URL those integration tests are skipped, not passed.
A clean extracted-package test is not a claim that every hosting vendor is certified,
nor a 24-hour soak test. Live signal publishing is intentionally not tested on your
real audience.
