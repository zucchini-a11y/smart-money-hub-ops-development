---
name: Session-open channel posts
description: Product scope and safety rules for the Smart Money Hub Market Analysis session-open posts.
---

**Rule:** Smart Money Hub Market Analysis may publish one additional weekday post for each of the Tokyo, London, and New York sessions, beyond the normal daily post limit. The owner wants Gemini to vary each post’s topic, headline, and layout using recent channel context, while preserving the Smart Money Hub brand and safety rules. Keep numeric times and timezone labels out of public session posts. If an opening is missed, generate a fresh time-free check-in and publish it only while that session remains active and all normal checks pass; after the session ends, keep it unpublished.

**Why:** The owner selected all three sessions, approved extra posts and same-day missed-session recovery, and asked for fresh professional content without public times. Session posts must remain distinct from signals and must not imply that a session opening is technical confirmation.

**How to apply:** Keep session posts separate from ordinary scheduled content. Use the configured Gemini model and archived channel context; rotate useful topics and layout patterns without repeating recent headlines or the last session layout. Calculate schedule times with IANA timezones and keep them in admin metadata, not public copy. A missed post may be regenerated and sent only within that session’s conventional local window; late copy must say the session is underway, contain no times, pass the same content/destination/permission checks, and publish once. Keep empty failed Gemini records reachable from admin controls with a retry action; refuse empty Gemini retries inside the final five-minute private-review window, while preserving the existing reviewed retry path for saved duplicate-content drafts. After the scheduled opening, retry only while the session is active, then refuse after close. Never invent live market facts or bypass the publishing pause, duplicate guard, or validators.

**Why:** The first failed-generation record exposed that ordinary recent-history views can omit empty drafts, leaving an active-session retry without an admin entry point.

**Rule:** Use the generated matching Tokyo, London, and New York session graphics as the respective session-post fallbacks. A photo attached to an individual post overrides that session’s default.

**Why:** The owner approved using the three distinct generated session graphics so the image matches the session being announced.

**How to apply:** Keep the three 16:9 graphics bundled with the bot code; select by session only when no admin-attached Telegram photo ID exists, and hold rather than silently omit a missing default image.
