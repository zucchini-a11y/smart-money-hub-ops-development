---
name: U.S. economic calendar scope
description: The selected source boundary for Smart Money Hub's USD and gold event calendar.
---

For the USD/XAU daily brief, retain the approved VAYDA Smart Money Hub template: USD & Macro Update, Gold Impact, Today's High-Impact Events, What Traders Should Watch, sources/check time, and NO CONFIRMATION, NO ENTRY. Use official U.S. records only, omit ISM and general/geopolitical headlines, and keep BLS/DOL unavailable until their sources are verified. Never infer missing values or timezones. If no significant verified development is available, say so without inventing news.

The daily brief is approved for 12:00 AM WAT delivery to the configured Market Analysis channel. Do not change that route or schedule without approval. The longer-term market-awareness scope may expand to Fed policy, Treasury data, and other instruments only when reliable sources and reuse rights are confirmed. GDELT is discovery only; leads require credible verification.

**Why:** the user approved the daily brief and its established template, while requiring the content to remain source-backed and honest about unavailable news or calendar fields.

**How to apply:** only describe facts supported by a verified source and timestamp. Hold affected items when a source is blocked, stale, timezone-ambiguous, or lacks redistribution permission; never route them to Market Analysis by default or imply automated trading.

For economic-event impact labels, show a rating only when a verified official source explicitly supplies it; otherwise mark the rating unavailable. Do not infer high/medium/low classifications with Gemini or another source.

**Why:** the user chose official ratings only and did not approve estimated impact labels.

**How to apply:** keep official-source event importance separate from cautious USD/gold relevance commentary; do not present interpretation as an official rating or market-direction prediction.

The weekly official USD/gold calendar is for the Education Suite Announcements topic (group -1003916437804, thread 3) at Monday 12:00 AM WAT. The daily brief remains in the configured Market Analysis channel and also runs at midnight.

**Why:** the user clarified that the weekly report is an Education Suite announcement, while the daily report belongs in the Market Analysis channel.

**How to apply:** preserve the daily schedule and destination; run the weekly calendar independently at Monday 00:00 WAT in the configured Education group’s verified Announcements topic, with separate idempotency and delivery records.

Thirty minutes before each daily or weekly brief, privately send the administrator the complete unpublished preview, destination, WAT publication time, and picture/no-picture actions. A picture may be read by Gemini only to match it to a currently verified official calendar record. The image is not a source of publishable facts; unsupported or conflicting claims are excluded. No reply or no picture must never delay the scheduled text brief; a verified picture is a separate companion post.

**Why:** the user wants the full news preview and an optional picture decision 30 minutes before publication, while keeping the scheduled text post on time.

**How to apply:** keep preview and image handling private/admin-only; use Gemini only to identify image-relevant official records, re-check those records before publication, and publish the complete verified text on schedule even if no picture is added or the image check fails.

The calendar review screen is private-admin-only and read-only. It must not trigger source fetches, scheduler work, or publishing, and Gemini must never fill missing source fields.

**Why:** the user explicitly required a review-only view that preserves source evidence without enabling live automation or inferred data.

**How to apply:** expose saved records through the private admin dashboard using read-only database access; keep source ingestion, scheduling, and Telegram publishing as separate capabilities.

As of 2026-10-25, direct requests in this Replit environment to both the official BLS release page and its `bls.ics` feed returned HTTP 403. The ICS parser can be tested with fixtures, but that is not evidence the live schedule was verified.

**Why:** the environment blocked both official endpoints, so the bot must not represent parsed fixture support as current BLS coverage.

**How to apply:** keep BLS marked unavailable until an actual official-source fetch succeeds; do not bypass the block with proxies or alternate unapproved sources.
