---
name: Telegram Business consent
description: Consent and retention safeguards for personal-account reply automation.
---

Before sending Telegram Business message text or conversation history to Gemini or another external API, obtain explicit opt-in from that chat participant. The opt-in notice must identify AI use, the external provider, the reply purpose, what text is retained, the retention period, and how to stop or delete it. Do not save or send message text before consent. Keep only the approved history, support opt-out/deletion, and erase content when the connection is disabled.

**Why:** Telegram’s Bot Developer Terms §5.4 require user authorization before Business message contents are disclosed to third-party APIs, and require clear disclosure of service scope and retained data.

**How to apply:** Treat the account owner’s Telegram Business connection and `can_reply` permission as separate from each contact’s data-processing consent. Track consent per private chat and require explicit opt-in before any model call.

## Current app state

Telegram Business automatic replies are disabled at the account owner's request. Do not process, retain, or send contact Business-message text to Gemini, and do not send consent or reply messages, unless the owner explicitly asks to re-enable the feature.

**Why:** The owner does not want contacts' messages processed and does not want them to receive the consent notice.

**How to apply:** Keep the runtime path disabled by default. If the owner requests the feature again, restore transparent opt-in before processing any contact text.

A separate private, admin-only reply-drafting tool may use writing examples and incoming-message text that the owner explicitly submits in a direct command. It sends drafts only back to the owner; it must not read Business chats or send messages to contacts. The owner can clear stored style examples.

**Why:** The owner wants replies to reflect their writing style but selected private drafts, not automatic Business-chat replies.

**How to apply:** Keep the draft feature isolated from the Business update route. Only transmit owner-submitted text and explicitly saved style examples for a draft request; never send the generated draft to the original sender.
