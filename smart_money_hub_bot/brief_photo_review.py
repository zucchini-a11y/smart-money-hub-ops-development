"""Private, optional photo prompts for the scheduled USD/gold briefs."""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)
WAT = ZoneInfo("Africa/Lagos")
PHOTO_PROMPT_LEAD_SECONDS = 5 * 60
_PHOTO_CALLBACK = re.compile(
    r"newsbrief:(photo|none):(daily|weekly):(\d{4}-\d{2}-\d{2})"
)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("photo_review_time_must_be_timezone_aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


class NewsBriefPhotoPrompts:
    """Persist photo requests and accept images only from the configured admin."""

    def __init__(
        self,
        api: TelegramAPI,
        database_path: str | Path,
        *,
        admin_id: int | None,
    ) -> None:
        self.api = api
        self.database_path = Path(database_path)
        self.admin_id = admin_id
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS news_brief_photo_reviews (
                    brief_type TEXT NOT NULL,
                    brief_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    photo_file_id TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (brief_type, brief_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS news_brief_photo_selection (
                    admin_id INTEGER PRIMARY KEY,
                    brief_type TEXT NOT NULL,
                    brief_date TEXT NOT NULL,
                    selected_at_utc TEXT NOT NULL
                )
                """
            )

    def send_prompt_if_due(
        self,
        brief_type: str,
        brief_date: date,
        scheduled_at: datetime,
        *,
        destination: str,
        now: datetime,
    ) -> bool:
        if brief_type not in {"daily", "weekly"} or self.admin_id is None:
            return False
        current = now.astimezone(timezone.utc)
        scheduled = scheduled_at.astimezone(timezone.utc)
        seconds_until = (scheduled - current).total_seconds()
        if not 0 < seconds_until <= PHOTO_PROMPT_LEAD_SECONDS:
            return False

        timestamp = _timestamp(current)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO news_brief_photo_reviews
                    (brief_type, brief_date, status, created_at_utc, updated_at_utc)
                VALUES (?, ?, 'prompting', ?, ?)
                """,
                (brief_type, brief_date.isoformat(), timestamp, timestamp),
            ).rowcount
        if inserted != 1:
            return False

        label = "Daily" if brief_type == "daily" else "Weekly"
        markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "📷 Add picture",
                        "callback_data": (
                            f"newsbrief:photo:{brief_type}:{brief_date.isoformat()}"
                        ),
                    },
                    {
                        "text": "No picture",
                        "callback_data": (
                            f"newsbrief:none:{brief_type}:{brief_date.isoformat()}"
                        ),
                    },
                ]
            ]
        }
        local_schedule = scheduled_at.astimezone(WAT)
        text = (
            f"{label} USD & Gold brief for {brief_date.strftime('%A, %d %B %Y')}\n"
            f"Destination: {destination}\n"
            f"Scheduled: {local_schedule.strftime('%H:%M WAT')}\n\n"
            "Would you like to add a picture? Tap “Add picture”, then send one "
            "image privately to this bot. If you do not reply or add a picture, "
            "the brief will still publish text-only at its scheduled time if "
            "the source and destination checks pass."
        )
        try:
            self.api.send_message(int(self.admin_id), text, markup)
        except Exception:
            self._set_status(brief_type, brief_date, "prompt_failed", now=current)
            logger.warning(
                "Could not deliver the private news-brief photo prompt (type=%s).",
                brief_type,
            )
            return False
        self._set_status(brief_type, brief_date, "awaiting_photo", now=current)
        return True

    def handle_callback(
        self,
        data: str,
        *,
        actor_id: int,
        chat_id: int,
        is_private: bool,
        now: datetime | None = None,
    ) -> bool:
        match = _PHOTO_CALLBACK.fullmatch(data)
        if match is None:
            return False
        if (
            self.admin_id is None
            or actor_id != self.admin_id
            or chat_id != self.admin_id
            or not is_private
        ):
            return True
        action, brief_type, raw_date = match.groups()
        try:
            brief_date = date.fromisoformat(raw_date)
        except ValueError:
            return True
        current = now or datetime.now(timezone.utc)
        if current.astimezone(WAT).date() >= brief_date:
            self._clear_selection()
            self.api.send_message(
                chat_id,
                "The photo window has ended. The brief will continue without a "
                "picture if its scheduled checks pass.",
            )
            return True

        status = self._status(brief_type, brief_date)
        if status != "awaiting_photo" and status != "photo_attached":
            self.api.send_message(
                chat_id,
                "This brief is no longer waiting for a picture. It will publish "
                "text-only at the scheduled time if checks pass.",
            )
            return True

        if action == "none":
            with closing(sqlite3.connect(self.database_path)) as connection, connection:
                connection.execute(
                    """
                    UPDATE news_brief_photo_reviews
                    SET status='no_photo', photo_file_id=NULL, updated_at_utc=?
                    WHERE brief_type=? AND brief_date=?
                    """,
                    (_timestamp(current), brief_type, brief_date.isoformat()),
                )
                connection.execute(
                    """
                    DELETE FROM news_brief_photo_selection
                    WHERE admin_id=? AND brief_type=? AND brief_date=?
                    """,
                    (self.admin_id, brief_type, brief_date.isoformat()),
                )
            self.api.send_message(
                chat_id,
                "Understood. It will publish text-only at the scheduled time if "
                "all checks pass.",
            )
            return True

        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                INSERT INTO news_brief_photo_selection
                    (admin_id, brief_type, brief_date, selected_at_utc)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(admin_id) DO UPDATE SET
                    brief_type=excluded.brief_type,
                    brief_date=excluded.brief_date,
                    selected_at_utc=excluded.selected_at_utc
                """,
                (
                    self.admin_id,
                    brief_type,
                    brief_date.isoformat(),
                    _timestamp(current),
                ),
            )
        self.api.send_message(
            chat_id,
            f"Send one picture now for the {brief_type} brief. If you want a "
            "picture on the other brief too, choose its “Add picture” button "
            "separately. The schedule will not be delayed.",
        )
        return True

    def handle_admin_photo(
        self,
        chat_id: int,
        sender_id: int,
        photos: list,
        *,
        is_private: bool,
        now: datetime | None = None,
    ) -> bool:
        if (
            not is_private
            or self.admin_id is None
            or chat_id != self.admin_id
            or sender_id != self.admin_id
        ):
            return False
        current = now or datetime.now(timezone.utc)
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT brief_type, brief_date
                FROM news_brief_photo_selection WHERE admin_id=?
                """,
                (self.admin_id,),
            ).fetchone()
        if row is None:
            return False
        brief_type, raw_date = str(row[0]), str(row[1])
        try:
            brief_date = date.fromisoformat(raw_date)
        except ValueError:
            self._clear_selection()
            return False
        if current.astimezone(WAT).date() >= brief_date:
            self._clear_selection()
            self.api.send_message(
                chat_id,
                "The scheduled time has arrived, so I could not attach that "
                "picture. The brief continues without it.",
            )
            return True

        file_id = ""
        if isinstance(photos, list) and photos:
            last_photo = photos[-1]
            if isinstance(last_photo, dict):
                candidate = last_photo.get("file_id")
                if isinstance(candidate, str) and 0 < len(candidate) <= 512:
                    file_id = candidate
        if not file_id:
            self.api.send_message(chat_id, "I couldn't read that picture. Try once more.")
            return True

        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                UPDATE news_brief_photo_reviews
                SET status='photo_attached', photo_file_id=?, updated_at_utc=?
                WHERE brief_type=? AND brief_date=?
                    AND status IN ('awaiting_photo', 'photo_attached')
                """,
                (file_id, _timestamp(current), brief_type, brief_date.isoformat()),
            )
            connection.execute(
                "DELETE FROM news_brief_photo_selection WHERE admin_id=?",
                (self.admin_id,),
            )
        self.api.send_message(
            chat_id,
            "Picture received. The brief will publish at its scheduled time if "
            "the source and destination checks pass.",
        )
        return True

    def photo_file_id(self, brief_type: str, brief_date: date) -> str | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT photo_file_id, status FROM news_brief_photo_reviews
                WHERE brief_type=? AND brief_date=?
                """,
                (brief_type, brief_date.isoformat()),
            ).fetchone()
        if row and row[1] == "photo_attached" and isinstance(row[0], str):
            return row[0]
        return None

    def mark_published(
        self, brief_type: str, brief_date: date, *, now: datetime
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                UPDATE news_brief_photo_reviews
                SET status='published', photo_file_id=NULL, updated_at_utc=?
                WHERE brief_type=? AND brief_date=?
                """,
                (_timestamp(now), brief_type, brief_date.isoformat()),
            )
        if self.admin_id is not None:
            with closing(sqlite3.connect(self.database_path)) as connection, connection:
                connection.execute(
                    "DELETE FROM news_brief_photo_selection WHERE admin_id=?",
                    (self.admin_id,),
                )

    def _status(self, brief_type: str, brief_date: date) -> str | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT status FROM news_brief_photo_reviews
                WHERE brief_type=? AND brief_date=?
                """,
                (brief_type, brief_date.isoformat()),
            ).fetchone()
        return str(row[0]) if row else None

    def _set_status(
        self,
        brief_type: str,
        brief_date: date,
        status: str,
        *,
        now: datetime,
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                UPDATE news_brief_photo_reviews
                SET status=?, updated_at_utc=?
                WHERE brief_type=? AND brief_date=?
                """,
                (status, _timestamp(now), brief_type, brief_date.isoformat()),
            )

    def _clear_selection(self) -> None:
        if self.admin_id is not None:
            with closing(sqlite3.connect(self.database_path)) as connection, connection:
                connection.execute(
                    "DELETE FROM news_brief_photo_selection WHERE admin_id=?",
                    (self.admin_id,),
                )


def send_brief_with_optional_photo(
    api: TelegramAPI,
    chat_id: int,
    report: str,
    *,
    photo_file_id: str | None,
    message_thread_id: int | None = None,
    photo_caption: str,
) -> tuple[int, str]:
    """Send the report first, then add an optional image without delaying it."""
    send_kwargs: dict[str, object] = {"parse_mode": "HTML"}
    if message_thread_id is not None:
        send_kwargs["message_thread_id"] = message_thread_id
    result = api.send_message_with_result(chat_id, report, **send_kwargs)
    message_id = result.get("message_id") if isinstance(result, dict) else None
    if not isinstance(message_id, int) or message_id <= 0:
        raise TelegramAPIError(
            "Telegram did not confirm the news-brief message.",
            delivery_unknown=True,
        )
    photo_status = "not_requested"
    if photo_file_id:
        try:
            result = api.send_photo_with_result(
                chat_id,
                photo_file_id,
                caption=photo_caption,
                message_thread_id=message_thread_id,
            )
            if isinstance(result, dict) and isinstance(result.get("message_id"), int):
                photo_status = "sent"
            else:
                photo_status = "delivery_unknown"
        except Exception as error:
            photo_status = (
                "delivery_unknown"
                if isinstance(error, TelegramAPIError) and error.delivery_unknown
                else "failed"
            )
            logger.warning(
                "Optional news-brief photo was not confirmed (status=%s).",
                photo_status,
            )
    return message_id, photo_status
