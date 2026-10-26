---
name: Telegram Business consent
description: Consent and retention safeguards for personal-account reply automation.
---

The owner wants automatic replies but does not want recipients to see an AI/data disclosure. Do not process Telegram Business messages with Gemini without that disclosure; keep automatic Business replies disabled and preserve the owner-only reply-drafting feature until the owner accepts a transparent setup.

**Why:** The owner explicitly rejected a recipient-facing AI notice. Private-message content must not be sent to an external AI service without clear disclosure.

**How to apply:** Do not instantiate or pass the personal Business reply assistant from the production entry point. Continue allowing the private admin-only `/replydraft` tool to process text the owner submits directly. Do not remove the disclosure requirement to restore automatic replies; ask the owner to choose a transparent setup first.

The separate private, admin-only `/replydraft` tool remains available for owner-submitted text and saved writing examples. It returns drafts only to the owner and never sends them to the original sender.

**Why:** Keep manual drafting distinct from the owner-authorized automatic Business reply flow.

**How to apply:** Only process text and style examples that the owner explicitly submits to the private draft command; never send the generated draft to the original sender.
