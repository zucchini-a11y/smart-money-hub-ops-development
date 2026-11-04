---
name: Admin text controls
description: The owner expects private-chat text to open and use the existing admin-menu actions.
---

Map clear owner text requests to the existing admin actions before routing the message to Coach. Keep text-based controls private and behind the same configured-admin authorization as button actions; ambiguous or unsupported requests should clarify rather than claim the bot cannot access its own saved queues. The owner also wants read-only operational status on request, including natural-language questions about queued posts, scheduled times, automatic publishing, and current posting state. One-off post requests must show a private preview before sending, and must stay within configured destinations.

**Why:** The owner asked to use text for everything available in the admin menu, wants broad bot status feedback when asked, reported that a held-post query incorrectly fell through to a Coach limitation response, and chose preview-before-send for on-demand posts.

**How to apply:** When adding or changing an admin capability, add natural-language shortcuts and test them through the Telegram update handler, while preserving authorization and the capability’s existing confirmation/publishing safeguards. Status summaries should report persisted facts and failures without triggering writes, sends, or publication; posting questions must read the actual saved queue and auto-publish setting.
