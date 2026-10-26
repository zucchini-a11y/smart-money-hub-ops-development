---
name: Telegram Business consent
description: Consent and retention safeguards for personal-account reply automation.
---

The owner approved automatic Telegram Business replies with a brief AI disclosure included in the first actual reply; do not send a separate YES/NO opt-in prompt.

**Why:** The owner wants hands-off replies without a separate consent prompt, but agreed recipients should be told briefly that replies use AI and recent context may be stored.

**How to apply:** When Gemini is configured and Telegram grants `can_reply`, automatically respond in private Business chats. Include the disclosure once in the first successful reply, not as a separate message. Preserve STOP/DELETE controls, bounded history, sensitive-message holds, duplicate protection, and the admin-only `/replydraft` feature.

The separate private, admin-only `/replydraft` tool remains available for owner-submitted text and saved writing examples. It returns drafts only to the owner and never sends them to the original sender.
