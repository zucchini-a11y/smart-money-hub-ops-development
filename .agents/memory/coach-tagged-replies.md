---
name: Private Coach replies
description: Keep private Coach replies threaded without displaying member names.
---

The Coach should reply directly to the member's incoming message in private chats, but must not add the member's username, name, or a mention entity to the reply text. This applies to text conversations, guided Coach answers, and private chart-image replies.

**Why:** The user explicitly said they do not want people's names shown in the bot's replies.

**How to apply:** Preserve Telegram reply threading with `reply_to_message_id`, but omit visible or hidden name/mention additions.
