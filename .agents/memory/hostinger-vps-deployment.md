---
name: Hostinger VPS deployment
description: Operational constraints for the Smart Money Hub bot running on Hostinger.
---

The Hostinger Ubuntu VPS is the live runtime for the Smart Money Hub Telegram bot. Changes made in Replit do not sync to the VPS automatically. The VPS code must be transferred and installed manually, and the Replit bot workflow must stay stopped while the VPS bot polls Telegram.

**Why:** Running two long-polling instances for the same bot can cause Telegram `getUpdates` conflicts or duplicate handling, while a Replit-only code change does not update the external VPS.

**How to apply:** Package only the tested files needed for a VPS update, transfer them through SFTP, preserve the current VPS files before replacing them, and restart the VPS service only after the upload. Verify its service state and polling heartbeat; do not restart the Replit bot.

### Operations Center domain hosting

The owner chose the Hostinger VPS for the Operations Center at `smartmoneyhub.tech`; `www` aliases the apex. Replit remains the development source, so web updates must be packaged and transferred manually. Preserve email and unrelated DNS records when changing the website target.

**Why:** The owner selected VPS hosting instead of Replit publishing for this domain.

**How to apply:** Serve the Operations Center from the VPS, keep HTTPS renewal enabled, and change only the apex website A record during future migrations. Do not imply the Operations Center has live bot telemetry unless that integration is built and verified.

### Public landing page isolation

Deploy the public landing page as a separate static release and route only `/` and its dedicated asset path to it. Keep existing `/login`, `/operations`, and `/api` handling in place; do not replace the shared Operations Center web root.

**Why:** The VPS domain also hosts the authenticated Support Portal and API, so replacing the shared site root can disrupt existing services.

**How to apply:** Back up the active Nginx site, verify Operations Basic Auth and an unauthenticated Support API response before and after the change, and reload Nginx only. Do not touch DNS, bot services, the database, or Production auth settings for a landing-page update.

### Telegram API address-family preference

On this Hostinger VPS, prefer IPv4 for outbound Telegram Bot API calls while leaving IPv6 enabled. Forced IPv4 reached `api.telegram.org` quickly, while IPv6 timed out; Python's Telegram send request consequently took about 20 seconds. The owner reported faster replies after the VPS began preferring IPv4.

**Why:** The delay was in the Telegram send call, not the database write or Gemini response. A quick request to the API root alone did not reveal the broken IPv6 route.

**How to apply:** When Telegram sends are slow, compare forced IPv4 and IPv6 and inspect the resolver's address order. Back up `/etc/gai.conf` before preferring IPv4, restart the bot, and verify an actual Bot API send; do not disable IPv6.

### Mobile terminal transfer reliability

When the owner operates Replit Shell and Termius on a phone, multiline pastes can be flattened and clipboard input can include terminal escape sequences. This can cause a public key to be run as a shell command or written incorrectly to `authorized_keys`.

**Why:** A failed key-only SFTP transfer led to repeated setup attempts while the owner was using mobile terminals.

**How to apply:** Prefer short, single-line commands. If key-only `scp` prompts for a password or fails, cancel instead of entering one; compare public-key fingerprints and inspect SSH authentication logs before retrying.
