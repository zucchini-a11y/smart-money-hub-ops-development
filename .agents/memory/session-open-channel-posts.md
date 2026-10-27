---
name: Session-open channel posts
description: Product scope and safety rules for the Smart Money Hub Market Analysis session-open posts.
---

**Rule:** Smart Money Hub Market Analysis may publish one additional weekday post for each of the Tokyo, London, and New York sessions, beyond the normal daily post limit. The owner wants Gemini to vary each post’s topic, headline, and layout using recent channel context, while preserving the Smart Money Hub brand and safety rules. Keep numeric times and timezone labels out of public session posts. If an opening is missed, generate a fresh time-free check-in and publish it only while that session remains active and all normal checks pass; after the session ends, keep it unpublished.

**Why:** The owner selected all three sessions, approved extra posts and same-day missed-session recovery, and asked for fresh professional content without public times. Session posts must remain distinct from signals and must not imply that a session opening is technical confirmation.

**How to apply:** Keep session posts separate from ordinary scheduled content. Use the configured Gemini model and archived channel context; rotate useful topics and layout patterns without repeating recent headlines or the last session layout. Calculate schedule times with IANA timezones and keep them in admin metadata, not public copy. A missed post may be regenerated and sent only within that session’s conventional local window; late copy must say the session is underway, contain no times, pass the same content/destination/permission checks, and publish once. Never invent live market facts or bypass the publishing pause, duplicate guard, or validators.
