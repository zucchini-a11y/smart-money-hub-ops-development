---
name: U.S. economic calendar scope
description: The selected source boundary for Smart Money Hub's USD and gold event calendar.
---

For the USD/XAU daily brief, retain the approved VAYDA Smart Money Hub template: USD & Macro Update, Gold Impact, Today's High-Impact Events, What Traders Should Watch, sources/check time, and NO CONFIRMATION, NO ENTRY. Use official U.S. records only, omit ISM and general/geopolitical headlines, and keep BLS/DOL unavailable until their sources are verified. Never infer missing values or timezones. If no significant verified development is available, say so without inventing news.

The daily brief is approved for 12:00 AM WAT delivery to the configured Market Analysis channel. Do not change that route or schedule without approval. The longer-term market-awareness scope may expand to Fed policy, Treasury data, and other instruments only when reliable sources and reuse rights are confirmed. GDELT is discovery only; leads require credible verification.

**Why:** the user approved the daily brief and its established template, while requiring the content to remain source-backed and honest about unavailable news or calendar fields.

**How to apply:** only describe facts supported by a verified source and timestamp. Hold affected items when a source is blocked, stale, timezone-ambiguous, or lacks redistribution permission; never route them to Market Analysis by default or imply automated trading.

The weekly official USD/gold calendar is for the Education Suite Announcements topic (group -1003916437804, thread 3) at Monday 12:00 AM WAT. The daily brief remains in the configured Market Analysis channel and also runs at midnight.

**Why:** the user clarified that the weekly report is an Education Suite announcement, while the daily report belongs in the Market Analysis channel.

**How to apply:** preserve the daily schedule and destination; run the weekly calendar independently at Monday 00:00 WAT in the configured Education group’s verified Announcements topic, with separate idempotency and delivery records.

Five minutes before each daily or weekly brief, privately ask the administrator whether to add a picture. No reply or no picture must never delay the scheduled text brief; any selected picture is a separate companion post, not a reason to truncate the sourced report.

**Why:** the user wants a chance to add an image but explicitly requires the brief to publish on time without waiting for one.

**How to apply:** keep the optional photo flow private and admin-only, persist selection safely across restarts, and publish the complete verified text at the scheduled time whether or not an image is attached.

The calendar review screen is private-admin-only and read-only. It must not trigger source fetches, scheduler work, or publishing, and Gemini must never fill missing source fields.

**Why:** the user explicitly required a review-only view that preserves source evidence without enabling live automation or inferred data.

**How to apply:** expose saved records through the private admin dashboard using read-only database access; keep source ingestion, scheduling, and Telegram publishing as separate capabilities.

As of 2026-10-25, direct requests in this Replit environment to both the official BLS release page and its `bls.ics` feed returned HTTP 403. The ICS parser can be tested with fixtures, but that is not evidence the live schedule was verified.

**Why:** the environment blocked both official endpoints, so the bot must not represent parsed fixture support as current BLS coverage.

**How to apply:** keep BLS marked unavailable until an actual official-source fetch succeeds; do not bypass the block with proxies or alternate unapproved sources.
