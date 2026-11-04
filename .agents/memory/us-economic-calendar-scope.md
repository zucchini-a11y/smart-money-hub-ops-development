---
name: U.S. economic calendar scope
description: The selected source boundary for Smart Money Hub's USD and gold event calendar.
---

Keep public USD/gold calendar briefs concise: list events and plain impact labels, and show a WAT time only when verified. Do not expose Gemini/provider attribution, source-health notes, links, or unavailable-field explanations in the channel post. Keep source provenance and health available in the admin-only review view. Use approved U.S. sources only, omit ISM and general/geopolitical headlines, and do not infer missing facts or timezones.

The daily brief is approved for 12:00 AM WAT delivery to the configured Market Analysis channel. Do not change that route or schedule without approval. The longer-term market-awareness scope may expand to Fed policy, Treasury data, and other instruments only when reliable sources and reuse rights are confirmed. GDELT is discovery only; leads require credible verification.

**Why:** the user wants a simple public event calendar with impact labels and does not want technical source details in the channel.

**How to apply:** use verified source records internally; omit unverified times, figures, and events from public display. Keep the full verification state in the admin view and never imply automated trading.

For economic-event impact labels, use a verified source rating when explicitly supplied. Otherwise Gemini may estimate High, Medium, Low, or Uncertain event importance from the verified event name, source, and date. Display only the plain impact value publicly; keep the model/provider provenance internal. Never infer a bullish or bearish price direction.

**Why:** the user chose plain impact labels without Gemini or official-rating wording in channel posts.

**How to apply:** send Gemini only eligible verified event records; cache estimates by event fingerprint so previews and scheduled posts match. Missing or invalid output remains unavailable, and estimates never change factual fields or become trading advice.

The weekly official USD/gold calendar is for the Education Suite Announcements topic (group -1003916437804, thread 3) at Monday 12:00 AM WAT. The daily brief remains in the configured Market Analysis channel and also runs at midnight.

**Why:** the user clarified that the weekly report is an Education Suite announcement, while the daily report belongs in the Market Analysis channel.

**How to apply:** preserve the daily schedule and destination; run the weekly calendar independently at Monday 00:00 WAT in the configured Education group’s verified Announcements topic, with separate idempotency and delivery records.

Thirty minutes before each daily or weekly brief, privately send the administrator the complete unpublished preview, destination, WAT publication time, and Edit news/Add picture/No picture actions. When the administrator selects Edit news, accept a complete replacement text and show the updated private preview; the scheduled post uses that replacement if final source and destination checks pass. When the administrator selects Add picture and sends an image, attach it as supplied even if Gemini cannot match it to a currently verified official calendar record. Only verified matches may add event details to the text; never use image-only claims to alter the brief. No reply, edit, or picture must delay the scheduled brief; an attached picture is a separate companion post.

**Why:** the user expects to review and optionally replace the news text or attach a picture before publication; failed image matching must not discard the picture or silently change verified news, and the scheduled text must remain on time.

**How to apply:** keep preview, replacement text, image transcription, and matching results private/admin-only. Preserve the administrator's full replacement as the scheduled text while retaining the existing final source/destination checks. Gemini should transcribe legible event rows from an admin-uploaded image even when no official records are available, clearly label those details as image observations, and never infer impact from icons. Only matches to fresh official records may add details from an image to the public brief; re-check those matches before publication and retain the admin-approved image independently. Publish on schedule even if no edit or picture is added or image analysis fails.

The calendar review screen is private-admin-only and read-only. It must not trigger source fetches, scheduler work, or publishing, and Gemini must never fill missing source fields.

**Why:** the user explicitly required a review-only view that preserves source evidence without enabling live automation or inferred data.

**How to apply:** expose saved records through the private admin dashboard using read-only database access; keep source ingestion, scheduling, and Telegram publishing as separate capabilities.

As of 2026-10-25, direct requests in this Replit environment to both the official BLS release page and its `bls.ics` feed returned HTTP 403. The ICS parser can be tested with fixtures, but that is not evidence the live schedule was verified.

**Why:** the environment blocked both official endpoints, so the bot must not represent parsed fixture support as current BLS coverage.

**How to apply:** keep BLS marked unavailable until an actual official-source fetch succeeds; do not bypass the block with proxies or alternate unapproved sources.
