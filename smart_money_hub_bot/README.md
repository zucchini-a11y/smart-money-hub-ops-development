# Smart Money Hub SMC Assessment Bot

A polling-based Telegram bot for a 10-question Smart Money Concepts assessment. It uses Python's standard library and Telegram's Bot API, with no Python package installs.

## Teaching principles in the assessment

- No confirmation, no entry; a CHoCH or POI alone is not an entry signal.
- No retest, no entry; do not chase price after it leaves the level.
- A point of interest needs a valid structural reason.
- Liquidity and displacement provide important context and confirmation, but neither guarantees a reversal.
- Define acceptable risk and a stop before entry; skip a trade rather than chase it.

## 1. Create a Telegram bot and get its token

1. In Telegram, open **@BotFather**.
2. Send `/newbot` and follow the prompts to choose a display name and a unique username.
3. Copy the token BotFather gives you. Treat it like a password; anyone with it can control your bot.

## 2. Add the token as a Replit Secret

1. Open this Replit project.
2. Open **Tools → Secrets**.
3. Add a secret named exactly `TELEGRAM_BOT_TOKEN`.
4. Paste the token from BotFather into its value field and save it.
5. Do not put the token in Python code, commit it to Git, or share it in chat.

The Telegram bot token is the only required credential.

## 3. Run the bot

After adding the secret, start the **Smart Money Hub Bot** workflow in Replit. The same command can be run from the project root:

```bash
python3 -m smart_money_hub_bot
```

If the secret has not been added, the bot prints a clear setup message and exits. It does not display or store the token in the project files.

This bot uses long polling. Only one running process should use a given bot token at a time. Telegram cannot poll while a webhook is active. At startup, the bot checks for an existing webhook and stops with an explanation if one is found; it does not change the webhook automatically.

## 4. Test the bot in Telegram

1. Open the bot using the username you selected with BotFather.
2. Send `/start`.
3. Press **Start SMC Test**.
4. Choose one of the four answer buttons for each of the 10 questions.
5. Confirm the final score, percentage, and explanations for missed questions.
6. Press **Take Test Again** to start another attempt.

## 5. Run the offline checks

These tests do not need a Telegram token or make network requests:

```bash
python3 -m unittest discover -s tests -v
```

## Saved results and session behavior

Completed attempts are stored in `data/smart_money_hub.sqlite3`. Each row contains the member's Telegram ID, Telegram username (if available), score, percentage, and UTC completion timestamp. Retakes create additional rows. The SQLite file is local to the Replit project and is excluded from Git.

Answers are kept in memory while an assessment is in progress; completed answers are not retained. If the process restarts mid-test, the member can start over. Completed scores remain in SQLite.

To use another database location, set `SMH_DATABASE_PATH` to a file path. The default directory and database are created automatically.

## Changing questions or extending grading later

- Edit question text, four options, the correct option index, and the explanation in `questions.py`.
- `scoring.py` contains deterministic multiple-choice grading, separate from Telegram message handling.
- `bot.py` owns the Telegram flow, and `storage.py` owns SQLite persistence.

To add written answers later, add a written-answer question type and route those responses through a separate grader module. The current version intentionally has no AI dependency and only offers multiple-choice questions.