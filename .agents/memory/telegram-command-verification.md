---
name: Telegram command verification
description: Verify user-facing Telegram command changes against the actual running bot.
---

Do not report a new Telegram command as active based only on a successful patch operation or a passing pre-existing test suite. Add a test that sends the exact command through the update handler, verify the expected reply, then restart the bot and confirm polling starts.

**Why:** A channel-ID diagnostic was reported active even though its handler was absent from the current source; the normal `/start` command still worked, which made the failure appear specific to admin access.

**How to apply:** For Telegram command work, check the resulting source and ensure the test count includes a named test for that new command before asking the user to try it.
