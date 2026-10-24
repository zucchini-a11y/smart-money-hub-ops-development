"""Application entry point for the Smart Money Hub Telegram bot."""

import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from .bot import SmartMoneyHubBot
from .channel_gemini import GeminiChannelContentService
from .coach import RuleBasedCoachService
from .gemini_coach import GeminiCoachService, GEMINI_MODEL
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
    admin_value = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
    try:
        admin_id = int(admin_value) if admin_value else None
    except ValueError:
        raise SystemExit("ADMIN_TELEGRAM_ID must contain a numeric Telegram user ID.") from None

    channel_value = os.getenv("SMH_MAIN_CHANNEL_ID", "").strip()
    try:
        main_channel_id = int(channel_value) if channel_value else None
    except ValueError:
        raise SystemExit(
            "SMH_MAIN_CHANNEL_ID must contain a numeric Telegram channel ID."
        ) from None

    reminder_timezone = os.getenv("SMH_REMINDER_TIMEZONE", "Africa/Lagos").strip()
    reminder_time = os.getenv("SMH_SUNDAY_REMINDER_TIME", "09:00").strip()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    coach_service = (
        GeminiCoachService(gemini_api_key)
        if gemini_api_key
        else RuleBasedCoachService()
    )
    channel_writer = (
        GeminiChannelContentService(gemini_api_key) if gemini_api_key else None
    )
    if gemini_api_key:
        logging.getLogger(__name__).info(
            "Gemini Coach enabled with the fixed free-tier model %s.", GEMINI_MODEL
        )
    else:
        logging.getLogger(__name__).info(
            "GEMINI_API_KEY is not configured; using the local Coach."
        )
    try:
        bot = SmartMoneyHubBot(
            TelegramAPI(token),
            str(database_path),
            admin_id=admin_id,
            main_channel_id=main_channel_id,
            reminder_timezone=reminder_timezone,
            reminder_time=reminder_time,
            coach_service=coach_service,
            channel_writer=channel_writer,
        )
    except (ValueError, ZoneInfoNotFoundError):
        raise SystemExit(
            "Check SMH_REMINDER_TIMEZONE and SMH_SUNDAY_REMINDER_TIME; "
            "use a valid timezone name and 24-hour time such as 09:00."
        ) from None
    try:
        bot.run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Smart Money Hub bot stopped.")


if __name__ == "__main__":
    main()