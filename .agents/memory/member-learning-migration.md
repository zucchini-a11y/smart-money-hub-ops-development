---
name: Member learning migration
description: Project rules for moving Smart Money Hub onboarding, lessons, progress, and follow-ups from Telegram to the website.
---

The website is the primary place for Smart Money Hub member onboarding, lessons, learning progress, routine follow-ups, and member communications. Telegram should become secondary for important notices and links; do not send full lessons, PDFs, routine learning follow-ups, or progress conversations there in the final design.

Keep the existing Telegram onboarding and follow-up workflows active until the website replacement is implemented, tested with Development identities, and explicitly approved for cutover. Never disable the live Telegram workflows during the Development build.

Keep PRO Signals eligibility separate from ordinary member learning. A member registration or Telegram identity link alone must not grant PRO access; preserve the verified funded-status and active-entitlement checks.

**Why:** the owner requested a staged website-first member journey while keeping current Telegram behavior available until a verified replacement is ready.

**How to apply:** build and validate changes in Development using `smh_test`; preserve current Telegram opt-outs and duplicate-prevention behavior; require explicit approval before changing Production, VPS services, DNS, or live bot delivery.
