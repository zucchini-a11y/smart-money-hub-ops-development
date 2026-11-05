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
