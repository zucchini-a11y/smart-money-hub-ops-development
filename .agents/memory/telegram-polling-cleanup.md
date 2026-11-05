---
name: Telegram polling cleanup
description: Diagnose duplicate Telegram getUpdates pollers when restarting this project's bot workflow.
---

Telegram permits only one active `getUpdates` poller per bot token. A workflow restart can leave an earlier local process alive while starting another one, producing `Conflict: terminated by other getUpdates request` even though the new process logged that polling started. A successful workflow-stop response did not always mean every bot process had exited in this workspace.

**Why:** A restart produced two local bot processes and Telegram polling conflicts. Stopping the managed workflow removed one process but left another attached to it.

**How to apply:** Before changing credentials, inspect running processes for the exact bot module. Stop the managed workflow, confirm its process exits, and only then start one instance. If a single local process still conflicts, check for another deployment or machine using the same bot token; do not rotate or expose the token as a first response.

### Scheduled publishing during a polling conflict

A `getUpdates` conflict does not necessarily stop the bot's independent scheduler. A local workflow can still publish a due channel post while repeated polling-conflict errors continue.

**Why:** The Replit workflow logged a New York session post during a run with recurring Telegram polling conflicts.

**How to apply:** Stop the unintended poller promptly, confirm its process exits, then compare channel-post records/logs from every intended instance before declaring whether a duplicate was sent.
