---
name: Public registration pause
description: Smart Money Hub policy for pausing member self-registration without blocking other access.
---

Keep public member self-sign-up disabled until the owner explicitly approves reopening. Existing member and staff sign-in, public pages, protected member feature routes, and separate PRO entitlements should continue working.

**Why:** The owner asked for only sign-up to be disabled while the rest of the site remains available.

**How to apply:** Block the public registration UI and route without changing sign-in or staff provisioning. Keep server-side member and PRO authorization intact, and confirm before reopening registration.
