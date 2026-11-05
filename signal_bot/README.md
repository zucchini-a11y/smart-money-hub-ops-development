# VAYDA SMART MONEY HUB

Portable Python Telegram bot for administrator-approved trading-community publishing.
It does not connect to a broker, place trades, invent market observations, or require
a paid AI or market-data service.

## Current storage and publishing status

- **Production: PostgreSQL** for trades, drafts, settings, applications, membership,
  publishing operations, receipts, and original/annotated chart bytes.
- **Tests: isolated SQLite plus real PostgreSQL integration tests.**
- Local chart files are a disposable cache, not the source of truth.
- **Publishing defaults to disabled.** Before each permitted send, the bot verifies
  the private administrator identity, their administrator role in both channels,
  distinct channel IDs, and the bot's posting/edit/invite permissions.
- This source runs on a standard Python host without a Replit runtime or AI Agent.

## Setup

Read **[docs/PORTABILITY.md](docs/PORTABILITY.md)** for full migration, hosting,
backup, restore, environment-variable, and shutdown instructions.
For an Ubuntu VPS setup plan and inactive systemd template, see
**[docs/VPS_UBUNTU_SETUP.md](docs/VPS_UBUNTU_SETUP.md)**. This does not deploy or start
the live bot.
For a dedicated always-on Python deployment on Replit, see
**[docs/REPLIT_RESERVED_VM_SETUP.md](docs/REPLIT_RESERVED_VM_SETUP.md)**. The source
packager includes a standalone Reserved VM `.replit` configuration in the ZIP.
Use **[docs/PRE_PRODUCTION_CHECKLIST.md](docs/PRE_PRODUCTION_CHECKLIST.md)** for exact
download/independent-backup steps and the gates that must precede live publishing.
For a separate test bot and private-only test instance, see
**[docs/PRIVATE_TEST_SETUP.md](docs/PRIVATE_TEST_SETUP.md)**. Never test publishing
with the running production workflow.

1. Install Python 3.12+ and run `python -m pip install -r requirements.txt`.
2. Configure PostgreSQL through `SMH_DATABASE_URL` (or `DATABASE_URL`).
3. On an external provider or development database:
   `python -m smh.admin_cli migrate --external-or-development`.
   Replit-managed production uses Publish's schema-diff process, not this command.
4. Configure Secrets/environment:
   `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `PRO_SIGNALS_CHANNEL_ID`,
    `MARKET_ANALYSIS_CHANNEL_ID`, and `EDUCATION_GROUP_ID`. `SMH_EDUCATION_LINK`
    is optional and may point to an HTTPS education site. PRO applications also require
    `EXNESS_PARTNER_LINK`; isolated tests use only `SMH_TEST_EXNESS_PARTNER_LINK`.
5. Keep `SMH_ALLOW_PUBLISHING=false` during setup/migration/recovery.
6. Add the bot as administrator in both channels: Post Messages, Edit Messages,
    Invite Users. The configured user must also administer both channels. For
    Educational Group access, add the bot and configured administrator to that group;
    the bot needs administrator status with **Invite Users** permission.
7. Run `python main.py`. Open the bot privately and use `/admin` and `/health`.
8. Only after verification and operator review, explicitly enable publishing through
   `SMH_ALLOW_PUBLISHING=true` and restart. No deployment automatically enables it.

`.env.example` has placeholders only. Actual environment files are never included
in the source archive. The program expects environment variables; it does not load
`.env` files automatically.

Members apply separately for PRO Signals, Market Analysis, and the Educational Group.
Approving one request never grants another destination. Each approved destination uses
its own time-limited invite: the Educational Group gets a one-use direct-join link,
while PRO Signals and Market Analysis use join-request links checked by the bot.
Access status, current invite, and membership are tracked separately. The bot rejects
stale, replaced, or another member's join request. An uncertain invite operation is not
retried automatically; review it in Operations.

PRO access has an additional three-part gate: the member registers through the configured
Exness partner link, an administrator manually verifies registration, and the
administrator privately reviews funding evidence and records it as verified before
giving final approval. The bot does not connect to Exness, inspect account data, or
infer funding from an image. Evidence is retained as a private Telegram file reference
in the database and can be viewed only by the administrator through the bot. Ask
applicants to crop passwords, OTPs, recovery codes, and login details before upload.
Existing PRO access is flagged for manual review on the next bot startup; access is not
automatically revoked.

PRO application outcomes are shown as `PENDING_REVIEW`, `MORE_INFORMATION_REQUIRED`,
`NOT_YET_ELIGIBLE`, `REJECTED`, or `APPROVED`. A pending registration or funding check
cannot be rejected just because it is still waiting. Applicants marked rejected or not
yet eligible can request Educational Group access, Market Analysis access, both in
sequence, or a fresh PRO eligibility review. Each alternative has its own application
and approval; selecting one does not grant access or create an invite automatically.
Applicants can resume registration or submit updated funding evidence privately. The bot
never asks for passwords, OTPs, or account credentials, and it does not pressure applicants
to deposit money.

Set `EDUCATION_GROUP_ID` to the negative Telegram chat ID of the production group in
Replit **Tools → Secrets**. For an isolated test instance, use only
`SMH_TEST_EDUCATION_GROUP_ID` with the private test group. Do not put either value in
source code. The existing `SMH_EDUCATION_LINK` welcome is sent only when the
administrator selected Educational Group access. If it is a Telegram invite URL, the
welcome uses the newly generated per-member expiring invite instead. If it is an
education website URL, the welcome button points to that site while the group invite
is sent separately. The isolated instance reads `SMH_TEST_EDUCATION_LINK`.

Development onboarding is opt-in through `SMH_TEST_EDUCATION_ONBOARDING_ENABLED`,
`SMH_TEST_EDUCATION_ANNOUNCEMENT_URL`, and
`SMH_TEST_EDUCATION_EPISODE_01_URL`. An optional
`SMH_TEST_EDUCATION_DEMO_ACCOUNT_URL` adds a Day 1 demo-account guide button.
Optional `SMH_TEST_EDUCATION_MARKET_STRUCTURE_VIDEO_URL` adds a separate Market
Structure video button to Day 2; Production uses `EDUCATION_MARKET_STRUCTURE_VIDEO_URL`.
`SMH_TEST_COACH_BOT_URL` adds a Coach link to the orientation and lesson; the
Production counterpart is `COACH_BOT_URL`. Onboarding refuses to enable until the
Coach link is configured. The link is only a handoff; shared Coach progress is not
implemented in this project.
Announcement and lesson links may point to a Telegram forum topic or a message in
that topic. Learners must start from Bot 1 and pass the
Education Group membership check before receiving Day 1 orientation; Episode 01 is
scheduled for the next Lagos calendar day. No later episode is generated without an
existing lesson record and link.

### Educational video lessons

See [docs/EDUCATION_VIDEOS.md](docs/EDUCATION_VIDEOS.md) for configuration, storage,
migration, backup, and safe testing details.

The owner can prepare an MP4 lesson in the Staff Support Portal’s Command Center,
review the exact caption and video, then choose **Publish lesson**. This route is
separate from member Education access and cannot target PRO Signals or Market Analysis.
The forum topic label defaults to **Video tutorials**. Configure
`SMH_EDUCATION_VIDEO_GROUP_ID` and `SMH_EDUCATION_VIDEO_TOPIC_ID` independently from
`EDUCATION_GROUP_ID`; use `SMH_TEST_EDUCATION_VIDEO_GROUP_ID` and
`SMH_TEST_EDUCATION_VIDEO_TOPIC_ID` for the isolated test destination. Production
still requires a separate group. In the isolated test environment only, the video
topic may share the Education forum if it differs from both the announcement and
Episode 01 topics.
Publication also requires the matching `SMH_ALLOW_PUBLISHING` or
`SMH_TEST_ALLOW_PUBLISHING` flag to be enabled. Leave production publishing disabled
until the destination, permissions, migration, backup, and test checklist are complete.

Video bytes are stored in the configured `SMH_*_EDUCATION_VIDEO_STORAGE_DIR` directory
(default `data/education-videos`; test default `data-test/education-videos`). The portal
API and corresponding bot process must share this same persistent directory. If they
run on separate hosts, mount the same persistent volume or set both variables to the
same shared storage location. Local disk is not an off-host backup; include this folder
in an independent backup. Application exports include video files and checksums.
An uncertain Telegram send is quarantined and never retried automatically.

## Telegram features

Commands: `/start`, `/myid`, `/admin`, `/health`, `/help`, `/cancel`.
Member commands: `/apply`, `/status`, `/education`, `/analysis`, `/pro`, and `/contact`.
Discover a channel ID by forwarding a channel post privately, or posting `/channelid`
in the channel after the administrator ID is configured.

### Private conversational assistant

Private messages without an active application step receive deterministic, rule-based
replies for common questions. The assistant has no required AI provider or paid API.
It recognizes common intents, provides FAQ topics, and offers clear buttons or an
administrator-contact option when it cannot answer. `/start` welcomes returning users
without repeating the first-time greeting and offers to resume a saved application.

Only a question explicitly submitted through **Contact Administrator** is stored and
shared with the administrator; other member messages are not copied into an admin
transcript. Support requests appear under **Member Support & FAQs**. The administrator
can reply with `/reply <case-id> <message>`, review FAQs with `/faq`, and update a
response using `/faq set <key> | <answer>`. `/assistant off` pauses automated topic
replies; `/apply`, `/status`, and administrator support remain available. If Telegram
does not confirm delivery of an admin reply, the request is marked uncertain and is
not automatically resent.

Common questions about membership, destination differences, registration, private
evidence, education, chart lessons, and community rules use editable database-backed
FAQ responses. The assistant never asks for passwords, OTPs, recovery codes, or
account credentials, and it does not verify Exness accounts or make trading decisions.

### Signals

Choose **New Zone** in the administrator menu. The bot asks one question at a time
for the market, symbol when needed, lower and upper prices, timeframe, required
confirmation, and expiry. Common markets, timeframes, and expiry periods use inline
buttons; use **Other** or **Skip** only where offered. Invalid answers keep the same
question open and explain what to correct. **Back**, **Cancel**, and **Return to Main
Menu** are available throughout the setup flow.

Review the complete setup, use **Edit** to correct a field, or choose **Cancel**.
**Confirm details** saves a draft only. If another setup is active, explicitly confirm
its replacement; then upload the matching chart and review it. The zone is not
published until you separately approve **Publish Zone + Chart**. Record only the
confirmation you actually observed; the bot never infers it. An unexpired, active,
unused zone and recorded confirmation are required before BUY NOW / SELL NOW can
publish to PRO Signals. A BUY/SELL signal replies to that setup post without
duplicating the chart. The signal says **NO CONFIRMATION, NO ENTRY** and never
fabricates entry, SL, or TP prices. Publishing stays hidden/locked until explicitly
enabled.

After Telegram confirms a send, the bot opens management controls for that trade and
original post. Uncertain sends go to reconciliation and are not retried. No market
hits, outcomes, partial closures, or broker orders are automatically detected or run.

Active Trades supports entry prices/zones, SL, TP1–TP100, target corrections/hits,
partial reports versus recommendations, breakeven instructions, trailing SL, setup
cancellation before activation, closure outcomes, custom updates, and original-post
editing. History filters include market, direction, status, and inclusive UTC dates.
All trade-management posts go only to PRO Signals. **Add Entry** collects an entry,
then asks for SL and TP before showing one reviewable update. `skip` leaves an
unsupplied value unchanged or unset; nothing is inferred. **Take Partial** combines
common percentages with the secured/recommendation choice, defaults to PRO Signals,
and allows an optional chart before one final post button.
After an instant BUY/SELL signal, **Set SL + TP together** accepts both confirmed
values in one message (for example, `SL 2580 | TP1 2700`) and shows one linked
review before publishing.
The first reported partial adds a risk-management reminder about considering
breakeven and securing partials. A second-partial message that says SL is at
breakeven appears only after the administrator explicitly confirms that action;
changing SL afterward clears that confirmation. The bot never moves a broker stop.

Channel messages keep trade, setup, and publishing-operation identifiers in the
database only. Trade updates reply to the original signal when Telegram permits;
if it cannot reply, the bot sends the clean update without a technical reference.
Review drafts use the same cleaned text that will be published. Older pending
drafts containing internal references are cleaned and require a fresh review.

### Analysis and charts

Prepare Market Analysis → caption/template → chart upload → local review → optional
manual field correction/annotations → original and edited preview → explicit Market
Analysis destination → administrator-approved publication.

The bot uses Tesseract only when that local executable is already installed. It makes
no network or paid-AI calls and does not require an AI key. OCR text is an unverified
candidate, not a market fact; the bot never infers price zones, structure, bias, or
confirmation from chart geometry. If local OCR is unavailable, those fields remain
**Unknown — manual review required**. The annotated review copy is watermarked and
does not draw unverified zones. Manually correct fields or add annotations before
approving the exact caption and image.

Manual annotation coordinates are percentages:

```
line 40 2650.50
zone 20 30 70 55 FVG
arrow 20 20 60 50 BOS
label 10 15 CHoCH
crop 5 5 95 95
resize 1600 900
```

Coordinates start at the top-left; commands apply in order. Supports undo and watermark.
Maximum upload 10 MB/24 megapixels; send a document to avoid Telegram photo compression.
Original received bytes remain unchanged. Charts outside Telegram photo constraints
are sent as documents. Captions are limited to 900 characters.

Routing and common direct trade-instruction patterns are validated server-side.
Free-form language and image contents cannot be perfectly classified: the administrator
must review them. No analysis is automatically converted to a signal.

### Members

Apply separately to each destination → five questions → administrator review. PRO
Signals additionally requires registration verification, private funding-evidence
review, and explicit final administrator approval. Registration alone never grants
access. Approved identity and destination-specific channel access are checked at join.
Beginners are not automatically rejected; no guarantee of trading profitability.

## Safety and recovery

Single polling worker, database session lock, persisted polling offset, single-use
recipient-bound buttons, trade version checks, transactions, persistent publishing
receipts, timeouts, capped network backoff, health monitor, watchdog, and graceful
shutdown.

Telegram does not accept caller-provided send idempotency keys. **Ambiguous sends
are quarantined, never blindly replayed.** Inspect the channel and reconcile an exact
existing message ID. This is administrator attestation, not automated historical
verification. Provider outages still require external supervision/operator recovery.

## Portable backup and restore

```
python -m smh.admin_cli export --file /secure-backups/vayda.zip
python -m smh.admin_cli restore --file /secure-backups/vayda.zip
python -m smh.admin_cli health
```

Exports include all application records plus chart files and a checksum/reference
manifest. Restore requires an empty migrated database and a stopped target worker.
It invalidates old buttons and marks interrupted sends uncertain. Keep encrypted,
off-host exports and managed database backups/PITR. Local backups alone are not
disaster recovery. Follow docs/PORTABILITY.md before moving hosts.

## Tests and source archive

```
python -m unittest discover -s tests -v
python tools/package_source.py
python tools/verify_release.py generated-artifacts/vayda-smart-money-hub-source.zip --safe-startup
```

For PostgreSQL integration tests, use a development/disposable `SMH_TEST_POSTGRES_URL`
or development `DATABASE_URL`. Never run tests against production. Without a PostgreSQL
test connection, integration tests are skipped, not passed.

`--safe-startup` verifies imports, database connectivity/schema metadata, and Telegram
identity/channel permissions without starting polling, sending messages, applying
migrations, or changing publishing settings. The legacy `--live-locked-start` option
is retained as an alias for compatibility; it no longer starts the bot.

The source-only archive contains the Python bot and tests, staff portal and API source,
migrations, pinned Python and Node dependencies, setup/deployment documentation,
`.env.example`, packaging/verification tools and a file checksum manifest. It
deliberately excludes private runtime exports, databases, uploaded charts, attachments,
actual secrets, caches and build outputs.

Live acceptance checklist: **docs/MANUAL_TEST_GUIDE.md**. Mocked Telegram tests are
not live-channel publishing tests; a clean deployment check is not a 24-hour soak test
or certification of every host.

## Staff support portal

The employee login, account provisioning, migration, and standard-host setup are
documented in **docs/SUPPORT_PORTAL.md**. The portal shares the bot's PostgreSQL
schema and does not publish to either Telegram channel.
