# Smart Money Hub AI Coach

A Python Telegram Bot API app for SMC education, assessments, trade journaling, and member accountability. The first version uses deterministic rules only; no AI provider or paid AI API is connected.

## Run & Operate

- Add `TELEGRAM_BOT_TOKEN` in **Tools → Secrets**, then run the **Smart Money Hub Bot** workflow.
- `python3 -m smart_money_hub_bot` — run the bot directly from the project root
- `python3 -m unittest discover -s tests -v` — run the offline test suite
- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string
- Bot secret: `TELEGRAM_BOT_TOKEN` — get it from Telegram's `@BotFather`; never put it in code
- Optional bot setting: `SMH_DATABASE_PATH` — defaults to `data/smart_money_hub.sqlite3`
- Optional admin secret: `ADMIN_TELEGRAM_ID` — numeric Telegram user ID shown by `/myid`
- Optional reminder settings: `SMH_REMINDER_TIMEZONE` (default `Africa/Lagos`) and `SMH_SUNDAY_REMINDER_TIME` (default `09:00`)

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Telegram bot: Python 3.11+ standard library and Telegram Bot API long polling
- Bot persistence: local SQLite; only Telegram Bot API credentials are required

## Where things live

- `smart_money_hub_bot/questions.py` — editable 10-question SMC assessment
- `smart_money_hub_bot/scoring.py` — deterministic answer checking and results
- `smart_money_hub_bot/telegram_api.py` — Telegram Bot API HTTP client
- `smart_money_hub_bot/bot.py` — Telegram menus, assessment, journal, check-in, progress, and reminders
- `smart_money_hub_bot/flows.py` — editable journal and check-in prompts
- `smart_money_hub_bot/education.py` — editable lesson cards
- `smart_money_hub_bot/grading.py` — provider-neutral written-answer evaluation interface with a deterministic implementation
- `smart_money_hub_bot/storage.py` — SQLite persistence and prior-score migration
- `smart_money_hub_bot/README.md` — setup, run, and test instructions

## Architecture decisions

- The current bot uses only Telegram and Python's standard library; no AI or paid API is required.
- Assessment questions, education content, flows, Telegram transport, grading, and persistence are separated so a future evaluator can be added without replacing the bot.
- The first version uses no OpenAI, Grok, or other AI service; the written-answer evaluator uses configured concepts and deterministic matching.
- In-progress conversations are held in memory; completed member records are stored in SQLite.
- Sunday reminders are opt-in, private-chat-only, and configurable; `/stop` unsubscribes.
- Run only one polling process for a given Telegram bot token.

## Product

Members can learn SMC, take a 10-question assessment, journal and review trades, complete weekly check-ins and Sunday preparation, manage opt-in reminders, and view their progress. Admin statistics are gated by `ADMIN_TELEGRAM_ID`. Member data and assessment-answer details are stored locally in SQLite.

Teaching principles: no confirmation, no entry; no retest, no entry; a POI needs a valid reason; liquidity and displacement matter; risk management comes before chasing a trade.

## User preferences

- Keep the first version dependent only on Python and the Telegram Bot API; do not add OpenAI, Grok, paid AI, or require an AI key.

## Gotchas

- Add the Telegram token through Replit Secrets before starting the bot workflow.
- Polling and a Telegram webhook cannot be used at the same time; startup detects an existing webhook and stops without changing it.
- Restarting the process clears in-progress flows, but does not remove completed SQLite records.
- Existing `assessment_results` rows are migrated into the assessment history and retained; old entries have no per-question answers or topic breakdown.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
- See `smart_money_hub_bot/README.md` for bot setup and operations
