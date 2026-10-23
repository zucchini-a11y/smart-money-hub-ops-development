---
name: Telegram typing indicator
description: Real Telegram verification for the Coach's typing status while preparing replies.
---

The typing indicator appeared in the member's Telegram chat during a Coach response after the bot sent and refreshed Telegram's `typing` chat action.

**Why:** The user confirmed the live indicator appeared, verifying behavior beyond mocked API tests.

**How to apply:** Retain the chat-action behavior for slow Coach responses; if revisiting it, distinguish a live Telegram confirmation from automated tests.
