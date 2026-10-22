---
name: Gemini free-tier policy
description: User-approved privacy and billing boundary for Gemini in Smart Money Hub Coach.
---

Smart Money Hub Coach may send a member's message and that member's bounded recent conversation history to Google Gemini on the free API tier. Keep the integration on the single configured free-tier model, leave billing disabled, and never silently fall back to a paid model.

**Why:** The user explicitly approved Google free-tier processing after learning that Google may use free-tier prompts to improve its products, while requiring no paid model or billing.

**How to apply:** Preserve per-member history isolation, do not send Telegram IDs or usernames, and use the existing local Coach when Gemini is unavailable or over quota.
