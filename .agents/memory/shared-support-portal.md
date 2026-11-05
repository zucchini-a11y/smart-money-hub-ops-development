---
name: Shared support portal
description: Architecture and environment boundaries for the Smart Money Hub support portal shared by Signal and Coach.
---

The Support Portal should be shared by both bots through one authenticated API and a common case store. Bots must not connect directly to each other's databases; bot identity, member ownership, and reply delivery must be enforced by the API. Keep test work isolated from production and require explicit approval before any production or VPS cutover.

**Why:** The owner chose one shared, login-first portal, while the bots use separate storage and deployments. Direct database sharing would couple unrelated bot runtimes and expose member cases across bot boundaries.

**How to apply:** Add new support flows through the shared API, scope every bot request to its authenticated bot and Telegram member, and keep Development data under `smh_test`. Do not publish or alter the VPS as part of a Development-only change.
