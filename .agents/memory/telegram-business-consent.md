---
name: Telegram Business consent
description: Consent and retention safeguards for personal-account reply automation.
---

The account owner has authorized automatic AI replies for enabled Telegram Business connections without requiring each contact to send YES. Before a chat's first message is sent to Gemini, deliver a concise disclosure naming AI and external AI processing, the retained context (up to six exchanges), STOP/DELETE controls, and minimal IDs retained for duplicate prevention. If that disclosure cannot be delivered, do not send the message to Gemini or reply.

**Why:** The owner explicitly chose automatic AI replies without a per-chat YES step. Telegram Business terms still require an accurate explanation of the bot's service and applicable data retention, and chats need an opt-out.

**How to apply:** Process only private chats on the owner’s enabled Telegram Business connection when Telegram grants `can_reply`. The first incoming message triggers the one-time disclosure before any Gemini call; then reply automatically. STOP disables that chat, START or YES re-enables it, DELETE clears stored text, and disconnecting the Business account clears connection data. Keep up to six completed exchanges, use owner-approved style examples only for surface tone, hold sensitive or consequential requests for the owner, and never fall back to the local Coach or retry an uncertain send.

The separate private, admin-only `/replydraft` tool remains available for owner-submitted text and saved writing examples. It returns drafts only to the owner and never sends them to the original sender.

**Why:** Keep manual drafting distinct from the owner-authorized automatic Business reply flow.

**How to apply:** The Business handler may use saved style samples for automatic replies, but the draft command remains private and owner-initiated.
