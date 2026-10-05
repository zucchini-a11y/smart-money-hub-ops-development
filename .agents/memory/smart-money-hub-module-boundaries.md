---
name: Smart Money Hub module boundaries
description: Prevent circular imports between the Telegram bot orchestrator and admin dashboard.
---

Keep the dependency direction one-way: `bot.py` may import `admin_dashboard.py`, but the dashboard must not import `bot.py`. Put shared dashboard constants in the dashboard module or a neutral module, and pass runtime dependencies into the dashboard.

**Why:** A reverse import caused the bot to crash during module initialization before it could contact Telegram or start polling.

**How to apply:** When adding bot features in separate modules, avoid importing the orchestrator for constants or helpers; move shared definitions down to a leaf module or inject them.
