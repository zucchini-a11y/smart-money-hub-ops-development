---
name: Hostinger VPS deployment
description: Operational constraints for the Smart Money Hub bot running on Hostinger.
---

The Hostinger Ubuntu VPS is the live runtime for the Smart Money Hub Telegram bot. Changes made in Replit do not sync to the VPS automatically. The VPS code must be transferred and installed manually, and the Replit bot workflow must stay stopped while the VPS bot polls Telegram.

**Why:** Running two long-polling instances for the same bot can cause Telegram `getUpdates` conflicts or duplicate handling, while a Replit-only code change does not update the external VPS.

**How to apply:** Package only the tested files needed for a VPS update, transfer them through SFTP, preserve the current VPS files before replacing them, and restart the VPS service only after the upload. Verify its service state and polling heartbeat; do not restart the Replit bot.
