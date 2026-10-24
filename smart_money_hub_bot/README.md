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
- **DM Coach:** private conversations route greetings, thanks, farewells, acknowledgements, SMC keywords, wins or losses, setup questions, and unrelated requests to different responses. Simple replies stay local and fast. When configured, Gemini provides natural responses using a bounded history retrieved only for that member. Genuine questions can be rated Helpful, Not helpful, or Still unclear. `/coach` opens the coaching menu.
- **Interactive coaching:** Chat with Coach, adaptive three-question SMC challenges, guided setup and mistake reviews, short lessons, and an optional daily knowledge challenge. Challenges rotate a larger question bank, avoid recent repeats, and adapt difficulty. They are started by the member; they are not sent as unsolicited DMs.
- **Reminders:** optional weekly Sunday check-in at 09:00 and automatic Monday/Thursday Zoom-class check-ins at 19:00 and 20:00 (`Africa/Lagos` by default). `/stop` turns off all scheduled reminders and `/resume` turns them back on. Members must start the bot in a private chat to receive DMs. A trade journal also returns an immediate review reminder.
- **Quick commands:** `/menu` opens the main menu, `/coach` opens coaching modes, `/clearcoach` asks to clear your saved Coach conversations, `/progress` shows a private progress summary, and `/reminders` shows the reminder schedule and controls. Progress and reminder details are only shown in a private chat.

The education and journal flows emphasize confirmation, retests, liquidity and displacement context, valid POIs, avoiding chase entries, and risk management. The bot is for education and record-keeping; it does not predict trades or promise profits. Back and Main Menu buttons are available through active flows.

The coach is a deterministic, offline rule-based system, not a general conversational AI. It handles known SMC concepts and common coaching situations, uses recent stored Coach exchanges to continue some follow-ups, and is explicit when a request is outside its scope. It does not see charts, check live prices, or know unrecorded preferences. No paid AI provider is connected or required.

## Find your Telegram ID and enable admin stats

1. Send `/myid` to the bot in a private chat.
2. Add a Replit Secret named `ADMIN_TELEGRAM_ID` with the numeric ID shown to you.
3. Restart **Smart Money Hub Bot**.
4. Send `/admin` to view the admin-only member, activity, assessment, journal, weekly participation totals, DM Coach statistics, Knowledge Improvement queue, one-time DM tool, and channel-promo tool.

The dashboard's **DM Coach Stats** page shows members using the coach, repeated questions, topics associated with reported process gaps, common mistakes, and recent activity. **Knowledge Improvement** groups repeated question examples, shows low-confidence items and negative feedback, and lets the admin research, draft, edit, approve, reject, version, or disable answers. The question queue does not show member usernames or IDs. Only the configured administrator can manage entries. Approved-answer retrieval is local and based on wording/category; Gemini is used for generated Coach replies, not to replace the approved-answer workflow.

### Optional Gemini Coach

- Add `GEMINI_API_KEY` as a Replit Secret using a Google AI Studio project that remains on the free tier with billing disabled. Never put the key in code or chat.
- The bot is pinned to Google's free-tier stable model `gemini-3.5-flash-lite`. It does not switch models or enable billing. On missing credentials, quota exhaustion, timeouts, or provider errors, the local Coach is used instead.
- Google says free-tier prompts may be used to improve its products. Only enable this if members' messages and their recent conversation context may be sent to Google under those terms.
- Up to six recent turns are loaded by Telegram user ID from the existing SQLite database. Telegram IDs and usernames are not sent to Gemini.

There is no automated web-research provider in the bot runtime. Selecting **Request more research** explicitly leaves an item awaiting research. The admin must research it outside the bot, then enter HTTPS source links, publication dates or limits as `NOTE:` lines, optional conflict notes, and an optional `REVIEW_BY: YYYY-MM-DD`. The bot stores links but does not fetch or verify page contents. Approval requires an answer and at least one HTTPS source; broker/platform and economic information also require a review date. Nothing becomes reusable knowledge until approved. Member feedback can reopen an item for review but never changes an approved answer automatically.

**Send One-Time DM** lets the admin write, preview, and confirm a plain-text DM to active private-chat members who have not used `/stop`; the admin is excluded. **Promote Bot in Channel** previews a single bot introduction in the configured channel and posts only after the admin confirms. Set `SMH_MAIN_CHANNEL_ID` to the channel's numeric ID. Admin access is not configured until `ADMIN_TELEGRAM_ID` is set. The bot never asks for your Telegram token in chat.

### Scheduled channel content

The admin dashboard's **Channel Content** page manages one post per day at **10:00 WAT (Africa/Lagos)** in the configured Market Analysis channel. The bot sends the administrator a preview the evening before at 18:00, or at 09:00 on the scheduled day if a preview is missing. The preview can be edited, published immediately, rejected, or skipped; scheduled publishing can also be paused and resumed. A draft not rejected or skipped is eligible for automatic publication at 10:00 after its preview has been delivered.

Posts rotate through education, weekly review, new-week preparation, engagement, and trading psychology. Until a verified market-data source is configured, the weekly recap slot uses an evergreen process review and does not state current prices, news, or market movements. Every post preserves **NO CONFIRMATION, NO ENTRY.** Bot-awareness content replaces a routine post about every two weekends by default; the administrator can change this to every weekend or every four weekends. Promotions use the runtime-verified bot username and link, and explain only implemented member features.

Before sending a post, the bot verifies that the configured destination is a channel whose title identifies it as Market Analysis and that this bot has posting permission. It does not post to PRO Signals. Posts, previews, admin actions, Telegram message IDs, and publication outcomes are recorded in SQLite. If a send's delivery is uncertain, the bot asks the administrator to check the channel before authorizing a retry, preventing an automatic duplicate.

## Reminder schedule

The default weekly check-in is Sunday at **09:00 Africa/Lagos**. Zoom-class reminders are sent at **19:00** and **20:00** on Mondays and Thursdays. Optional environment variables:

- `SMH_REMINDER_TIMEZONE` — an IANA timezone, default `Africa/Lagos`.
- `SMH_SUNDAY_REMINDER_TIME` — 24-hour local time, default `09:00`.
- `SMH_MAIN_CHANNEL_ID` — numeric ID of the Telegram channel for admin-confirmed bot promotions.
- `SMH_DATABASE_PATH` — SQLite file location, default `data/smart_money_hub.sqlite3`.

Only members who have started the bot in a private chat are eligible for automatic Zoom-class check-ins. Sunday check-ins remain optional. `/stop` disables all scheduled reminders until the member resumes them in Reminder Settings. If Telegram reports that a chat is blocked or unavailable, all reminders for that member are stopped. Each scheduled reminder is recorded to prevent duplicates across workflow restarts.

## Data and editing

SQLite stores members, assessments and individual answers, trades, weekly check-ins, Sunday preparations, progress, reminder deliveries, DM coaching interactions, anonymized question examples, feedback, and approved knowledge versions. Recent coaching interactions provide per-member conversational continuity; no member's history is mixed with another's. `/clearcoach` deletes that member's coaching interactions, related Coach mistake notes, feedback, and their question examples. Approved generalized knowledge and its version history remain. It does not delete assessments, trade journal records, or reminder settings. The default database file is local to the Replit project and excluded from Git. Existing score rows from the earlier assessment-only bot are migrated into the new assessment history without deleting the original records. Older attempts did not retain individual answers, so their topic breakdowns are unavailable.

Editable content is in:

- `questions.py` — assessment questions, options, answers, and explanations.
- `education.py` — short lesson text.
- `flows.py` — guided journal and check-in prompts.
- `grading.py` — deterministic written-answer rubric behind a replaceable evaluator interface. No AI connection is enabled.
- `coach.py` — local SMC explanations, the provider interface, and deterministic fallback.
- `gemini_coach.py` — direct Gemini API client pinned to the free-tier model, with bounded history and sanitized error handling.
- `message_router.py` — routes simple conversation intents, approved knowledge matches, and fallback Coach replies.
- `question_detection.py`, `knowledge_base.py`, and the `knowledge_*.py` modules — question triage, lexical retrieval, research/draft validation, approval, versions, and member feedback.

In-progress conversations are kept in memory and can be restarted if the workflow stops. Completed member records are stored in SQLite.

## Test the complete flows

### From Telegram

1. Send `/start`, open **💬 Ask Coach**, test “Hi”, “Good morning”, “Thanks”, “Okay”, and “Bye”. Then compare “What is BOS?”, “Explain break of structure”, and “What does BOS mean?”.
2. Test a trade loss, “Gold hit my TP today,” an unknown question, and “Should I buy Gold now?”. Unknown/current questions should be flagged rather than guessed.
3. Ask “What is CHOCH?” and reply to its follow-up; the next reply should continue that topic. Complete **Challenge Me** twice and confirm the questions vary, then try **Daily Challenge**.
4. Try **Review My Setup** and **Review My Mistake**. Send `/clearcoach` to see the confirmation, then cancel it or confirm to clear only your Coach history.
5. Open **Start SMC Assessment**. Answer all 10 questions; check the score, topic feedback, missed answers, and explanations.
6. Open **Trading Journal** → **New Trade Entry**. Complete all 15 prompts, then use **Review Previous Trades** to retrieve the saved entry.
7. Complete **Weekly Check-In** and **Sunday Preparation**. Open **My Progress** to confirm the check-in and journal data appear.
8. Open **Learn SMC** and select a lesson.
9. In **Reminder Settings**, opt in to the Sunday reminder, then send `/stop` to unsubscribe.
10. Send `/myid`, configure `ADMIN_TELEGRAM_ID` as a Replit Secret, restart the workflow, and send `/admin`; open **DM Coach Stats**.
11. Open **Knowledge Improvement**. Test a known concept question and an unsupported or current-information question; inspect the anonymous queue, add researched HTTPS sources, draft an answer, and approve it. Confirm that an approved matching question uses that answer, while a negative member rating creates a review candidate without changing it.

### Offline tests

These checks need no Telegram token and make no network requests:

```bash
python3 -m unittest discover -s tests -v
```