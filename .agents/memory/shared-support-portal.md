---
name: Shared support portal
description: Architecture and environment boundaries for the Smart Money Hub support portal shared by Signal and Coach.
---

The Support Portal should be shared by both bots through one authenticated API and a common case store. Bots must not connect directly to each other's databases; bot identity, member ownership, and reply delivery must be enforced by the API. Production cutover must preserve existing staff access and support history rather than replacing the current portal schema. Keep test work isolated from production and require explicit approval before any production or VPS cutover.

**Why:** The owner chose one shared, login-first portal, while the bots use separate storage and deployments. The VPS already has support records and staff accounts, so recreating its schema could break staff access or lose case history.

**How to apply:** Add new support flows through the shared API, scope every bot request to its authenticated bot and Telegram member, and keep Development data under `smh_test`. Before production changes, review a schema-only export and use an additive migration that preserves current accounts and cases. Do not publish or alter the VPS as part of a Development-only change. A portal-only production rollout may start with staff authentication and no bot tokens; bot endpoints must reject requests until each bot's matching token is configured. Portal availability alone does not mean Signal or Coach ingestion is connected.

**Why:** The owner needs the shared domain portal before the separate bot processes have their production bridge credentials configured.

### Visual direction

The owner selected the VAYDA portal's forest-green, warm-cream, and muted-gold visual language for the shared Support Portal. Keep the existing authenticated support API and case workflow; do not import unrelated portal modules as part of a visual update.

**Why:** The owner asked for the domain portal to match the existing VAYDA portal design while preserving the current shared-case product.

**How to apply:** Use the supplied VAYDA source as the visual reference for support login, navigation, and case-workspace styling. Keep feature and backend migrations separate unless the owner requests them.

### VPS API database credentials

The Node Support API must use a dedicated PostgreSQL login with a generated SCRAM password stored in a root-only file, and it should receive grants only on Support Portal tables. Do not blindly reuse the bot's database URL: it may rely on OS/peer authentication and contain no password.

**Why:** The production Node `pg` client failed with `client password must be a string` when the bot's database URL was reused.

**How to apply:** Keep the bot's database environment unchanged. Provision a restricted API role, store its random password with mode `0600`, and grant only the support schema/tables the API uses.

### Existing portal schema compatibility

Keep portal authentication compatible with both legacy `admin`/`agent` roles and the existing `owner`/`manager`/`agent` roles. `CREATE TABLE IF NOT EXISTS` does not add columns to a pre-existing portal table; use explicit additive migrations in Development. When adding password-state tracking to existing accounts, default it to false so current staff are not unexpectedly forced to reset passwords.

**Why:** The imported portal's login selected a password-state column absent from the existing Development table, causing a 503; the existing owner role also differed from the imported code's legacy role names.

**How to apply:** Inspect Development columns and role constraints before relying on imported migrations, add only the missing schema in `smh_test`, and preserve the existing role values and credentials. Do not apply the Development compatibility migration to the VPS without an approved production rollout.
