---
name: Replit bot workflow scope
description: The user's instruction for stopping noisy Replit bot workflows and distinguishing them from VPS services.
---

Keep Replit Smart Money Hub bot and WhatsApp bot workflows stopped unless the user explicitly asks to start them. Development owner diagnostics must use separate `SMH_TEST_*` Telegram credentials for read-only `getMe` checks; never reuse live bot tokens or start polling as part of a connection check. Replit workspace edits and workflow state do not automatically alter the separately deployed Hostinger VPS.

**Why:** duplicate pollers cause Telegram conflicts and unexpected activity; the user asked to stop Replit bots and distinguish Replit Development from VPS Production.

**How to apply:** stop Replit bot workflows when requested and keep them stopped until explicitly restarted. For Owner dashboard checks, report identity separately from runtime health, use only isolated Development credentials/data, and leave VPS bots unchanged unless the user separately authorizes a VPS service action.
