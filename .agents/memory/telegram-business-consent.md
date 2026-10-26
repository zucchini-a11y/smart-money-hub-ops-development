---
name: Telegram Business consent
description: Consent and retention safeguards for personal-account reply automation.
---

Before sending Telegram Business message text or conversation history to Gemini or another external API, obtain explicit opt-in from that chat participant. The opt-in notice must identify AI use, the external provider, the reply purpose, what text is retained, the retention period, and how to stop or delete it. Do not save or send message text before consent. Keep only the approved history, support opt-out/deletion, and erase content when the connection is disabled.

**Why:** Telegram’s Bot Developer Terms §5.4 require user authorization before Business message contents are disclosed to third-party APIs, and require clear disclosure of service scope and retained data.

**How to apply:** Treat the account owner’s Telegram Business connection and `can_reply` permission as separate from each contact’s data-processing consent. Track consent per private chat and require explicit opt-in before any model call.
