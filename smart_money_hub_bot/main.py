"""Application entry point for the Smart Money Hub Telegram bot."""

import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

from .bot import SmartMoneyHubBot
from .channel_gemini import GeminiChannelContentService
from .coach import RuleBasedCoachService
from .daily_calendar_brief import DailyCalendarBriefPublisher
from .brief_photo_review import NewsBriefPhotoPrompts
from .gemini_coach import GeminiCoachService, GEMINI_MODEL
from .group_features import (
    DEFAULT_EDUCATION_GROUP_ID,
    EDUCATION_ANNOUNCEMENTS_THREAD_ID,
)
from .personal_reply_assistant import PersonalTelegramReplyAssistant
from .storage import DEFAULT_DATABASE_PATH
from .telegram_api import TelegramAPI
from .weekly_calendar_brief import WeeklyCalendarBriefPublisher


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

    education_group_value = os.getenv(
        "SMH_EDUCATION_GROUP_ID", str(DEFAULT_EDUCATION_GROUP_ID)
    ).strip()
    try:
        education_group_id = int(education_group_value)
    except ValueError:
        raise SystemExit(
            "SMH_EDUCATION_GROUP_ID must contain a numeric Telegram group ID."
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
    personal_reply_assistant = (
        PersonalTelegramReplyAssistant(gemini_api_key) if gemini_api_key else None
    )
    reply_draft_assistant = (
        PersonalTelegramReplyAssistant(gemini_api_key) if gemini_api_key else None
    )
    if gemini_api_key:
        logging.getLogger(__name__).info(
            "Gemini Coach enabled with the fixed free-tier model %s.", GEMINI_MODEL
        )
        logging.getLogger(__name__).info(
            "Scheduled Market Analysis posts use the primary Gemini model only; "
            "provider failures hold the draft."
        )
    else:
        logging.getLogger(__name__).info(
            "GEMINI_API_KEY is not configured; using the local Coach and holding "
            "weekend AI drafts."
        )
    if personal_reply_assistant is not None:
        logging.getLogger(__name__).info(
            "Telegram Business automatic replies are enabled when the connected "
            "account grants can_reply; the first reply includes a brief AI disclosure."
        )
    else:
        logging.getLogger(__name__).info(
            "Telegram Business automatic replies are disabled because Gemini is "
            "not configured; the owner-only reply-drafting feature remains available."
        )
    if admin_id is not None and main_channel_id is not None and channel_writer is not None:
        logging.getLogger(__name__).info(
            "Tokyo, London, and New York session-open Market Analysis posts are enabled "
            "for weekdays; Gemini drafts 15 minutes before each open, a private "
            "review is sent 5 minutes before, and eligible drafts publish at the open."
        )
    else:
        logging.getLogger(__name__).info(
            "Session-open Market Analysis posts are inactive because an administrator, "
            "destination channel, or Gemini writer is not configured."
        )
    try:
        daily_brief_enabled = os.getenv(
            "SMH_DAILY_USD_GOLD_BRIEF_ENABLED", "false"
        ).strip().casefold() in {"1", "true", "yes", "on"}
        daily_calendar_brief = None
        weekly_brief_enabled = os.getenv(
            "SMH_WEEKLY_USD_GOLD_BRIEF_ENABLED", "false"
        ).strip().casefold() in {"1", "true", "yes", "on"}
        brief_photo_prompts = (
            NewsBriefPhotoPrompts(
                TelegramAPI(token),
                str(database_path),
                admin_id=admin_id,
            )
            if admin_id is not None and (daily_brief_enabled or weekly_brief_enabled)
            else None
        )
        weekly_calendar_brief = None
        if daily_brief_enabled:
            if admin_id is None or main_channel_id is None:
                logging.getLogger(__name__).error(
                    "Daily USD/Gold brief is enabled but admin or Market Analysis "
                    "channel configuration is missing; publisher remains disabled."
                )
            else:
                daily_calendar_brief = DailyCalendarBriefPublisher(
                    TelegramAPI(token),
                    str(database_path),
                    admin_id=admin_id,
                    channel_id=main_channel_id,
                    photo_prompts=brief_photo_prompts,
                )
                logging.getLogger(__name__).info(
                    "Daily USD/Gold official calendar brief enabled for 00:00 WAT."
                )
        if weekly_brief_enabled:
            if admin_id is None or education_group_id is None:
                logging.getLogger(__name__).error(
                    "Weekly USD/Gold brief is enabled but admin or Education Suite "
                    "group configuration is missing; publisher remains disabled."
                )
            else:
                weekly_calendar_brief = WeeklyCalendarBriefPublisher(
                    TelegramAPI(token),
                    str(database_path),
                    admin_id=admin_id,
                    group_id=education_group_id,
                    thread_id=EDUCATION_ANNOUNCEMENTS_THREAD_ID,
                    photo_prompts=brief_photo_prompts,
                )
                logging.getLogger(__name__).info(
                    "Weekly USD/Gold official calendar brief enabled for Monday "
                    "00:00 WAT in the Education Suite Announcements topic; "
                    "the daily brief remains in Market Analysis."
                )
        bot = SmartMoneyHubBot(
            TelegramAPI(token),
            str(database_path),
            admin_id=admin_id,
            main_channel_id=main_channel_id,
            reminder_timezone=reminder_timezone,
            reminder_time=reminder_time,
            coach_service=coach_service,
            channel_writer=channel_writer,
            education_group_id=education_group_id,
            education_market_analysis_topic_link=os.getenv(
                "SMH_EDUCATION_MARKET_ANALYSIS_TOPIC_LINK", ""
            ).strip(),
            daily_calendar_brief=daily_calendar_brief,
            weekly_calendar_brief=weekly_calendar_brief,
            news_brief_photo_prompts=brief_photo_prompts,
            personal_reply_assistant=personal_reply_assistant,
            reply_draft_assistant=reply_draft_assistant,
        )
        logging.getLogger(__name__).info(
            "Education-group morning learning posts scheduled daily for 08:00 WAT; "
            "weekly Education polls remain scheduled for Saturday 21:00 WAT."
        )
        logging.getLogger(__name__).info(
            "Education-group Market Analysis promotions are scheduled for Monday and "
            "Thursday at 19:00 WAT; the 18:55 private preview is optional to review, "
            "and eligible posts publish automatically after final checks."
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