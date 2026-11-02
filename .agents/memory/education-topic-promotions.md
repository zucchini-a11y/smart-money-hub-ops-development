---
name: Education topic promotion publishing
description: Owner-approved publishing and recovery rules for Monday/Thursday Education-group promotions.
---

Scheduled Monday/Thursday Education-group promotions should publish automatically at their scheduled WAT time without waiting for admin approval, provided generation, content validation, destination verification, and Telegram delivery checks pass. A private preview is useful for optional edits or a photo, but it is not an approval gate.

**Why:** the owner explicitly asked for these scheduled promotions to post on time without approval.

**How to apply:** preserve automatic publishing for eligible drafts. If the scheduler misses the preview tick, recover only within the configured on-time grace window; after it expires, hold the promotion rather than posting late. Keep cancellation, incomplete edits, failed checks, and destination changes as blockers.
