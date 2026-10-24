---
name: U.S. economic calendar scope
description: The selected source boundary for Smart Money Hub's USD and gold event calendar.
---

For the first USD/XAU calendar phase, use official U.S. sources, omit ISM and general/geopolitical headlines, and keep BLS/DOL unavailable until their sources are verified. Never infer missing values or timezones. The longer-term market-awareness scope may expand to Fed policy, Treasury data, and other instruments only when reliable sources and reuse rights are confirmed. GDELT is discovery only; leads require credible verification.

Keep the USD & Gold destination unset until the user supplies and approves it. Sunday at 7:00 PM WAT is the proposed weekly brief time, not authorization to enable automation or delivery.

**Why:** the user approved an official-source-first calendar, then expanded the product goal to broader market awareness while requiring source, licensing, and cost checks before use.

**How to apply:** only describe facts supported by a verified source and timestamp. Hold affected items when a source is blocked, stale, timezone-ambiguous, or lacks redistribution permission; never route them to Market Analysis by default or imply automated trading.

The calendar review screen is private-admin-only and read-only. It must not trigger source fetches, scheduler work, or publishing, and Gemini must never fill missing source fields.

**Why:** the user explicitly required a review-only view that preserves source evidence without enabling live automation or inferred data.

**How to apply:** expose saved records through the private admin dashboard using read-only database access; keep source ingestion, scheduling, and Telegram publishing as separate capabilities.
