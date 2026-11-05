---
name: Hostinger VPS deployment
description: Operational constraints for the Smart Money Hub bot running on Hostinger.
---

The Hostinger Ubuntu VPS is the live runtime for the Smart Money Hub Telegram bot. Changes made in Replit do not sync to the VPS automatically. The VPS code must be transferred and installed manually, and the Replit bot workflow must stay stopped while the VPS bot polls Telegram.

**Why:** Running two long-polling instances for the same bot can cause Telegram `getUpdates` conflicts or duplicate handling, while a Replit-only code change does not update the external VPS.

**How to apply:** Package only the tested files needed for a VPS update, transfer them through SFTP, preserve the current VPS files before replacing them, and restart the VPS service only after the upload. Verify its service state and polling heartbeat; do not restart the Replit bot.

### Telegram API address-family preference

On this Hostinger VPS, prefer IPv4 for outbound Telegram Bot API calls while leaving IPv6 enabled. Forced IPv4 reached `api.telegram.org` quickly, while IPv6 timed out; Python's Telegram send request consequently took about 20 seconds. The owner reported faster replies after the VPS began preferring IPv4.

**Why:** The delay was in the Telegram send call, not the database write or Gemini response. A quick request to the API root alone did not reveal the broken IPv6 route.

**How to apply:** When Telegram sends are slow, compare forced IPv4 and IPv6 and inspect the resolver's address order. Back up `/etc/gai.conf` before preferring IPv4, restart the bot, and verify an actual Bot API send; do not disable IPv6.
