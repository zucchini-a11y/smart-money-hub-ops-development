---
name: Bot downtime recovery
description: How to detect and communicate Telegram bot recovery after a long outage.
---

Measure bot downtime from persisted successful Telegram poll timestamps, not from a member's inactivity. After an outage of at least 30 minutes, send a professional apology/status notice on each member's next private interaction; do not broadcast unsolicited recovery messages.

**Why:** The user clarified that the bot's inactivity—not the member's—should be acknowledged professionally.

**How to apply:** Keep polling-health state durable across workflow restarts, measure downtime from the next poll's start to avoid counting long-poll waiting time, send each member one notice per recovery event, and continue their active flow or message handling after the notice.
