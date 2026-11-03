---
name: Routine channel publish limit
description: Manual recovery rules for missed scheduled Market Analysis routine posts.
---

An administrator may publish an eligible past-scheduled routine Market Analysis post on the current WAT date once its scheduled time has passed, provided no other routine post is already published, publishing, awaiting retry, or has uncertain delivery that day. The chosen post uses that day's routine-post slot; later routine posts must remain held rather than creating a second one. Keep this limit scoped to the routine scheduled-channel-post flow, not the separate session-open posts or Education-group posts.

**Why:** A strict requirement that the current date match the original schedule date made the admin's Publish Now control unusable for held posts, while simply removing the restriction could allow two routine posts on one WAT day.

**How to apply:** Keep the manual action available for eligible drafts and failures after their scheduled time. Enforce the current WAT day's slot atomically when reserving publication, and continue to run destination, content, approval, and duplicate checks.
