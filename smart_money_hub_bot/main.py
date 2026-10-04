"""Application entry point for the Smart Money Hub Telegram bot."""

import logging
import os
from pathlib import Path

from .bot import SmartMoneyHubBot
from .storage import DEFAULT_DATABASE_PATH
from .telegram_api import TelegramAPI


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Missing TELEGRAM_BOT_TOKEN. Add your bot token in Replit Tools > "
            "Secrets, then start the Smart Money Hub Bot workflow again."
        )

    database_path = Path(
        os.getenv("SMH_DATABASE_PATH", str(DEFAULT_DATABASE_PATH))
    )
    bot = SmartMoneyHubBot(TelegramAPI(token), str(database_path))
    try:
        bot.run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Smart Money Hub bot stopped.")


if __name__ == "__main__":
    main()