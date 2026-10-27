---
name: Bot downtime recovery
description: How to detect and communicate Telegram bot recovery after a long outage.
---

Measure bot downtime from persisted successful Telegram poll timestamps, not from a member's inactivity. After an outage of at least 30 minutes, send a varied professional recovery notice only when the incoming message was sent during that outage; do not apologize for messages sent after recovery or broadcast unsolicited notices.

**Why:** The user clarified that the bot should not apologize when a person sends a new message after it is already back online.

**How to apply:** Keep polling-health state durable across workflow restarts, measure downtime from the next poll's start to avoid counting long-poll waiting time, compare Telegram message timestamps with that outage interval, rotate notice wording per member across recoveries, and continue the member's active flow after a valid delayed-message notice.
