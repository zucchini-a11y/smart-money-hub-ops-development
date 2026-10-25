---
name: Sunday check-in audience
description: The user's audience and opt-out rule for recurring Sunday check-in messages.
---

Send the weekly Sunday check-in by default to users who have started the bot in a private chat. Honor a member's Sunday reminder opt-out and the global `/stop`; group-only contacts are not eligible for private messages. Keep existing Off settings as opt-outs during migration.

**Why:** The user requested Sunday check-ins for all bot starters, excluding anyone who opted out. Existing Off settings cannot distinguish an earlier explicit choice from the old opt-in default, so preserve them as opt-outs.

**How to apply:** Keep the existing Sunday schedule and duplicate prevention. New private starters default to receiving the check-in, and members can disable it in Reminder Settings or stop all reminders with `/stop`.
