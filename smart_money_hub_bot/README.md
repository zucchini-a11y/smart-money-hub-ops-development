# Smart Money Hub AI Coach

A Python Telegram Bot API application for SMC education, assessment, trading journals, and accountability. It uses the Python standard library and SQLite. The first version does not call OpenAI, Grok, or any other AI provider or paid AI service.

## Start the bot

1. In Telegram, open **@BotFather**, create a bot with `/newbot`, and copy the token.
2. In Replit, open **Tools → Secrets** and add `TELEGRAM_BOT_TOKEN`. Do not put the token in code or chat.
3. Start the **Smart Money Hub Bot** workflow.
4. Open your bot in Telegram and send `/start`.

The bot uses long polling. Run only one process with this token at a time. Telegram cannot poll while a webhook is active; if one is configured, the bot stops and explains the issue without changing the webhook.

## Member features

- **SMC Assessment:** 10 multiple-choice questions, score and percentage, topic strengths and areas to review, plus explanations for every missed answer.
- **Trading Journal:** guided entry for all 15 requested trade details, a structured educational review, and retrieval of saved trades.
- **Weekly Check-In:** trade counts, process and discipline review, biggest mistake, and focus for the next week.
- **Sunday Preparation:** weekly goal, SMC focus, mistake to avoid, and a plan for missed setups.
- **My Progress:** assessment history totals and averages, latest score, journaled trades and outcomes, strongest and weakest topics, common mistake, and recent check-ins.
- **Learn SMC:** short lessons on structure, BOS/CHoCH, liquidity, order blocks, FVG/IFVG, POIs, confirmation, retests, risk, and psychology.
- **DM Coach:** members can send private SMC questions or describe a setup for deterministic, guided coaching on the framework, confirmation, retests, risk, and trade reviews. Ask Coach is available from the main menu; `/coach` opens it directly. No AI provider or paid API is connected.
- **Reminders:** optional weekly Sunday check-in at 09:00 and automatic Monday/Thursday Zoom-class check-ins at 19:00 and 20:00 (`Africa/Lagos` by default). `/stop` turns off all scheduled reminders. Members must start the bot in a private chat to receive DMs. A trade journal also returns an immediate review reminder.

The education and journal flows emphasize confirmation, retests, liquidity and displacement context, valid POIs, avoiding chase entries, and risk management. The bot is for education and record-keeping; it does not predict trades or promise profits. Back and Main Menu buttons are available through active flows.

## Find your Telegram ID and enable admin stats

1. Send `/myid` to the bot in a private chat.
2. Add a Replit Secret named `ADMIN_TELEGRAM_ID` with the numeric ID shown to you.
3. Restart **Smart Money Hub Bot**.
4. Send `/admin` to view the admin-only member, activity, assessment, journal, weekly participation totals, and DM Coach statistics.

The dashboard's **DM Coach Stats** page shows members using the coach, repeated questions, topics associated with reported process gaps, common mistakes, and recent activity. Admin access is not configured until that secret is set. The bot never asks for your Telegram token in chat.

## Reminder schedule

The default weekly check-in is Sunday at **09:00 Africa/Lagos**. Zoom-class reminders are sent at **19:00** and **20:00** on Mondays and Thursdays. Optional environment variables:

- `SMH_REMINDER_TIMEZONE` — an IANA timezone, default `Africa/Lagos`.
- `SMH_SUNDAY_REMINDER_TIME` — 24-hour local time, default `09:00`.
- `SMH_DATABASE_PATH` — SQLite file location, default `data/smart_money_hub.sqlite3`.

Only members who have started the bot in a private chat are eligible for automatic Zoom-class check-ins. Sunday check-ins remain optional. `/stop` disables all scheduled reminders until the member resumes them in Reminder Settings. If Telegram reports that a chat is blocked or unavailable, all reminders for that member are stopped. Each scheduled reminder is recorded to prevent duplicates across workflow restarts.

## Data and editing

SQLite stores members, assessments and individual answers, trades, weekly check-ins, Sunday preparations, progress, reminder deliveries, and DM coaching interactions with detected topics, possible mistakes, and lessons. The default database file is local to the Replit project and excluded from Git. Existing score rows from the earlier assessment-only bot are migrated into the new assessment history without deleting the original records. Older attempts did not retain individual answers, so their topic breakdowns are unavailable.

Editable content is in:

- `questions.py` — assessment questions, options, answers, and explanations.
- `education.py` — short lesson text.
- `flows.py` — guided journal and check-in prompts.
- `grading.py` — deterministic written-answer rubric behind a replaceable evaluator interface. No AI connection is enabled.
- `coach.py` — rule-based DM Coach behind a provider-neutral service interface; `ai_evaluate_answer()` currently delegates to the local rules.

In-progress conversations are kept in memory and can be restarted if the workflow stops. Completed member records are stored in SQLite.

## Test the complete flows

### From Telegram

1. Send `/start`, open **💬 Ask Coach**, ask “What is CHOCH?”, and try “I saw an FVG and entered immediately.” Then send “I got stopped out” and answer the review checklist.
2. Open **Start SMC Assessment**. Answer all 10 questions; check the score, topic feedback, missed answers, and explanations.
3. Open **Trading Journal** → **New Trade Entry**. Complete all 15 prompts, then use **Review Previous Trades** to retrieve the saved entry.
4. Complete **Weekly Check-In** and **Sunday Preparation**. Open **My Progress** to confirm the check-in and journal data appear.
5. Open **Learn SMC** and select a lesson.
6. In **Reminder Settings**, opt in to the Sunday reminder, then send `/stop` to unsubscribe.
7. Send `/myid`, configure `ADMIN_TELEGRAM_ID` as a Replit Secret, restart the workflow, and send `/admin`; open **DM Coach Stats**.

### Offline tests

These checks need no Telegram token and make no network requests:

```bash
python3 -m unittest discover -s tests -v
```