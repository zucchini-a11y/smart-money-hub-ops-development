# Smart Money Hub AI Coach

A Python Telegram Bot API application for SMC education, assessment, trading journals, and accountability. It uses the Python standard library and SQLite, with optional Google Gemini access on the configured free tier. It does not use paid AI services.

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
- **Reminders:** weekly Sunday check-in at 09:00 for private-chat starters by default, plus automatic Monday/Thursday Zoom-class check-ins at 19:00 and 20:00 (`Africa/Lagos` by default). Members can turn the Sunday check-in off; `/stop` turns off all scheduled reminders and `/resume` turns them back on. Members must start the bot in a private chat to receive DMs. A trade journal also returns an immediate review reminder.
- **Quick commands:** `/menu` opens the main menu, `/coach` opens coaching modes, `/clearcoach` asks to clear your saved Coach conversations, `/progress` shows a private progress summary, and `/reminders` shows the reminder schedule and controls. Progress and reminder details are only shown in a private chat.

The education and journal flows emphasize confirmation, retests, liquidity and displacement context, valid POIs, avoiding chase entries, and risk management. The bot is for education and record-keeping; it does not predict trades or promise profits. Back and Main Menu buttons are available through active flows.

When Gemini is configured, the private Coach can answer general questions as well as trading-education questions, using recent saved Coach exchanges for relevant follow-ups. It cannot see live channel posts, inspect charts, check live prices, or know unrecorded preferences. If Gemini is unavailable, the local rule-based Coach can still handle supported SMC concepts and common coaching situations; it cannot provide general AI answers.

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

The admin dashboard's **Channel Content** page manages one post per day in the configured Market Analysis channel. Monday–Saturday posts are scheduled for **10:00 WAT (Africa/Lagos)**; Sunday posts are scheduled for **18:00 WAT**. The administrator receives a private preview at 18:00 on the preceding evening (Friday for Saturday; Saturday for Sunday). If that preview is missing, the bot tries again one hour before the scheduled time. Drafts can be revised with Gemini feedback, edited directly, published immediately, rejected, or skipped; publishing can be paused and resumed. Eligible unreviewed drafts are automatically published after a timely preview, unless rejected, skipped, or paused.

Session-open posts are additional weekday Market Analysis posts for Asia (Tokyo 09:00 JST), London (08:00 Europe/London), and New York (08:00 America/New_York). The schedule uses each session's IANA timezone and converts to WAT across daylight-saving changes. Gemini prepares an evergreen post 15 minutes before the open; the admin receives the complete review 5 minutes before, can approve/edit/cancel or add a photo, and an eligible post publishes at the open if there is no response. Session drafts appear under **Channel Content → Session Open Posts**. The same channel pause, destination verification, formatting and factual-claim checks apply; Gemini failures are held, not replaced with local or alternate-model content. These are conventional FX session markers, not exchange-guaranteed hours.

Weekend drafts use the configured primary Gemini model only. Gemini receives recent posts from the configured channel that the bot has archived, scheduled-post history, and saved admin revision feedback. New and edited channel posts are archived for future context; Telegram does not provide the bot with older channel history on demand, so pre-existing history is unavailable unless separately supplied. No external market-data source is configured, so posts must remain evergreen and must not claim live prices, news, or market movements. A Gemini error, unusable response, unsafe content, or duplicate draft leaves that day's post held for admin review; the bot does not substitute a local template or another model. The failure is recorded and the administrator is notified; retry is manual. Every post preserves **NO CONFIRMATION, NO ENTRY.** Bot-awareness content replaces a routine Saturday post about every two weekends by default; the administrator can change this to every weekend or every four weekends. Promotions require a runtime-verified bot username and link and may describe only verified member features.

Weekday posts continue to use the existing reviewed local content. Before any post is sent, the bot verifies the configured destination is the Market Analysis channel and that the bot can post there. It does not publish to PRO Signals. Posts, previews, AI-generation results, admin actions, destination, Telegram message IDs, and publication outcomes are recorded in SQLite. Uncertain Telegram delivery requires an administrator check before retrying, to prevent duplicate posts.

Before sending a post, the bot verifies the configured Market Analysis channel ID, confirms Telegram returns a channel rather than a group or test destination, and checks that this bot has posting permission. The currently selected channel's Telegram title is “Smart Money Hub.” Posts, previews, admin actions, Telegram message IDs, and publication outcomes are recorded in SQLite. If a send's delivery is uncertain, the bot does not retry automatically, preventing a duplicate.

### Daily official USD and gold calendar brief

The isolated daily calendar publisher sends one verified USD and gold calendar brief per Africa/Lagos date at **00:00 WAT** when `SMH_DAILY_USD_GOLD_BRIEF_ENABLED=true`. It uses the already-configured Market Analysis channel (`SMH_MAIN_CHANNEL_ID`) and does not alter weekday/weekend post times, Education polls, signals, or PRO Signals. SQLite records each date's delivery status and Telegram message ID; an uncertain Telegram send is never retried automatically. A missed 15-minute publication window is skipped rather than posted late.

The daily brief uses official BEA records; source refresh also checks the official Census, BLS, and Federal Reserve calendars and records DOL as unavailable until its information can be verified. Only timestamps with a verified source timezone are converted to WAT. Census dates and times remain unconverted while its timezone is unverified, and FOMC meeting windows do not imply a decision-release time. Forecasts, previous values, actuals, and impact levels are shown as unavailable unless supplied by a verified source. A failed BEA refresh or destination/permission check holds that day's channel post and privately notifies the administrator.

Thirty minutes before each scheduled daily or weekly brief, the bot privately sends the complete unpublished preview, its destination and WAT publication time, and **Add picture** / **No picture** actions to the administrator. If the administrator does not respond or does not attach an image, the text brief still publishes at the scheduled time if its source and destination checks pass. Gemini can inspect an attached image only to match it to a currently verified official calendar record. It cannot supply or change a figure, date, time, impact rating, or market claim. A verified match is reflected in an image-related source-backed highlight, and the picture is sent as a separate companion after the complete text. Unmatched or unverifiable images are not used or posted; image-review or delivery failures never delay the text brief.

### Weekly official USD and gold calendar

The separate weekly brief runs at **Monday 00:00 WAT** when `SMH_WEEKLY_USD_GOLD_BRIEF_ENABLED=true`. It posts to the Education Suite's **Announcements** forum topic (group `SMH_EDUCATION_GROUP_ID`, thread 3). The daily brief remains in the configured Market Analysis channel; both distinct briefs run at midnight. The weekly brief uses only verified official U.S. release records, does not use Gemini to fill gaps, and excludes ISM, geopolitical headlines, and unrelated events. Census entries show dates only until the source timezone is verified. Missing forecasts, previous figures, actual results, and impact classifications remain explicitly unavailable. A five-minute source-check reuse window prevents a second burst of source requests after the daily publisher has refreshed the same calendars. A missed 15-minute WAT publication window is skipped rather than sent late; persistent SQLite state prevents duplicate weekly sends after a restart.

### Broader USD and gold news intelligence (not activated)

The separate `news_intelligence.py` module includes source parsing, SQLite history, deduplication and revision tracking, GDELT lead verification, timezone-aware event formatting, source-bounded Gemini analysis, and private-admin alert drafts. It is **not wired into the bot polling loop or channel publisher**. No geopolitical alert, Treasury-yield update, Gemini macro analysis, or public weekly-report update is sent automatically. Do not treat this separate capability as part of the daily official calendar brief.

## Reminder schedule

The Sunday check-in is sent at **09:00 Africa/Lagos** to private-chat starters by default. A member can turn it off in Reminder Settings; `/stop` disables every scheduled reminder. Zoom-class reminders are sent at **19:00** and **20:00** on Mondays and Thursdays. Optional environment variables:

- `SMH_REMINDER_TIMEZONE` — an IANA timezone, default `Africa/Lagos`.
- `SMH_SUNDAY_REMINDER_TIME` — 24-hour local time, default `09:00`.
- `SMH_MAIN_CHANNEL_ID` — numeric ID of the Telegram channel for admin-confirmed bot promotions.
- `SMH_DATABASE_PATH` — SQLite file location, default `data/smart_money_hub.sqlite3`.

Only members who have started the bot in a private chat can receive DMs. New private-chat starters receive the Sunday check-in unless they turn it off; members whose existing Sunday setting was Off remain excluded during migration. `/stop` disables all scheduled reminders until the member resumes them in Reminder Settings. If Telegram reports that a chat is blocked or unavailable, all reminders for that member are stopped. Each scheduled reminder is recorded to prevent duplicates across workflow restarts.

## Data and editing

SQLite stores members, assessments and individual answers, trades, weekly check-ins, Sunday preparations, progress, reminder deliveries, DM coaching interactions, anonymized question examples, feedback, and approved knowledge versions. Recent coaching interactions provide per-member conversational continuity; no member's history is mixed with another's. `/clearcoach` deletes that member's coaching interactions, related Coach mistake notes, feedback, and their question examples. Approved generalized knowledge and its version history remain. It does not delete assessments, trade journal records, or reminder settings. The default database file is local to the Replit project and excluded from Git. Existing score rows from the earlier assessment-only bot are migrated into the new assessment history without deleting the original records. Older attempts did not retain individual answers, so their topic breakdowns are unavailable.

Editable content is in:

- `questions.py` — assessment questions, options, answers, and explanations.
- `education.py` — short lesson text.
- `flows.py` — guided journal and check-in prompts.
- `grading.py` — deterministic written-answer rubric behind a replaceable evaluator interface. No AI connection is enabled.
- `coach.py` — local SMC explanations, the provider interface, and deterministic fallback.
- `gemini_coach.py` — direct Gemini API client pinned to the free-tier model, with bounded history and sanitized error handling.
- `channel_gemini.py` — primary-model-only scheduled Market Analysis post writer; failures never fall back to local or alternate-model content.
- `news_intelligence.py` — isolated, currently inactive news-source adapters, verification, persistence, calendar formatting, and verified-fact Gemini analysis.
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

## Education-group morning notes

The bot schedules one short Education-group learning note per Africa/Lagos date
at **08:00 WAT** when the administrator has enabled scheduled content. The
publisher allows up to 30 minutes of late delivery after downtime; after that
window, the day's post is recorded as skipped rather than sent late. New
installations remain paused until `/contentresume`; `/contentpause` pauses it.
It uses a vetted evergreen lesson bank and a persistent
SQLite delivery ledger; exact message variations are not reused. Recent
admin-authored and bot-authored group posts and stored quiz topics are used
locally to reduce topic repetition. The bot cannot reconstruct Telegram history
that it did not receive and archive. Saturday morning notes mention the existing
weekly Education poll at **21:00 WAT**; that poll schedule remains unchanged.
If the bot misses the five-minute delivery window, the destination cannot be
verified, or a send has uncertain delivery, it holds or skips the post and
notifies the administrator rather than sending late or retrying a possible
duplicate. This group feature does not use Gemini or send to the Market
Analysis channel.