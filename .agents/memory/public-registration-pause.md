---
name: Public landing-page scope
description: Smart Money Hub public website scope, destination buttons, and member registration pause.
---

Keep the public website to one uncluttered landing page. The primary onboarding-bot button is labeled “Join Us”; link it to the verified Smart Money Hub onboarding bot and show the existing onboarding message after the visitor taps Start. Keep Market Analysis and PRO Signals destinations separate; do not add a large destination-card grid. Public member sign-up is approved for Development and Production builds using the existing email-verification flow. Registration grants neither staff access nor PRO Signals entitlement. Preserve server-side authorization and separate staff/member permissions.

**Why:** The owner corrected an overly crowded landing-page redesign, changed the primary bot button label to “Join Us,” asked for destination buttons instead of packed-in feature sections, and later explicitly approved reopening sign-in and sign-up in both environments.

**How to apply:** Keep page content focused on the existing landing-page layout. Use button-styled controls for account actions and verified destinations. Reuse the current Clerk flow; require verified email before member access, never grant staff/PRO entitlements through registration, and remember that the live VPS domain needs its own authorized release.
