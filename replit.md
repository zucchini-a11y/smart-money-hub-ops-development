# Smart Money Hub SMC Assessment Bot

A Python Telegram bot that tests Smart Money Hub members on Smart Money Concepts and stores completed scores locally.

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
- `smart_money_hub_bot/bot.py` — Telegram commands, quiz sessions, and result messages
- `smart_money_hub_bot/storage.py` — local SQLite score records
- `smart_money_hub_bot/README.md` — setup, run, and test instructions

## Architecture decisions

- The current bot uses only Telegram and Python's standard library; no AI or paid API is required.
- Questions, transport, scoring, and persistence are separate so a future written-answer grader can be added without replacing the quiz flow.
- Active quiz answers are held in memory; completed scores are stored in SQLite.
- Run only one polling process for a given Telegram bot token.

## Product

Members start a 10-question multiple-choice SMC assessment in Telegram, get a score out of 10 and percentage, review explanations for incorrect answers, and can retake it. Each completed result records the Telegram ID, username, score, and UTC completion date locally.

Teaching principles: no confirmation, no entry; no retest, no entry; a POI needs a valid reason; liquidity and displacement matter; risk management comes before chasing a trade.

## User preferences

- Keep the bot dependent only on Python and the Telegram Bot API.

## Gotchas

- Add the Telegram token through Replit Secrets before starting the bot workflow.
- Polling and a Telegram webhook cannot be used at the same time; startup detects an existing webhook and stops without changing it.
- Restarting the process clears in-progress quiz sessions, but does not remove completed SQLite records.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
- See `smart_money_hub_bot/README.md` for bot setup and operations
