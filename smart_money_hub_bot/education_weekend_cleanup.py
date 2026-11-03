"""Weekend cleanup for the bot's tracked Education-group lesson and poll."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .telegram_api import TelegramAPIError

logger = logging.getLogger(__name__)
CLEANUP_ZONE = ZoneInfo("Africa/Lagos")
CLEANUP_TIME = time(23, 0)
TELEGRAM_DELETE_WINDOW = timedelta(hours=48)
RECOVERY_WINDOW = timedelta(hours=24)


def _as_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


class EducationWeekendCleanupStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS education_weekend_cleanup_items (
                    cleanup_date TEXT NOT NULL,
                    target_kind TEXT NOT NULL CHECK (
                        target_kind IN (
                            'saturday_lesson', 'sunday_lesson', 'saturday_poll'
                        )
                    ),
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    sent_at_utc TEXT,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'deleted', 'skipped')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at_utc TEXT,
                    failure_category TEXT,
                    failure_notified INTEGER NOT NULL DEFAULT 0,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (cleanup_date, target_kind)
                )
                """
            )
            schema = connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'table' AND name = 'education_weekend_cleanup_items'
                """
            ).fetchone()
            if schema and "saturday_lesson" not in str(schema[0]):
                connection.execute(
                    "ALTER TABLE education_weekend_cleanup_items "
                    "RENAME TO education_weekend_cleanup_items_legacy"
                )
                connection.execute(
                    """
                    CREATE TABLE education_weekend_cleanup_items (
                        cleanup_date TEXT NOT NULL,
                        target_kind TEXT NOT NULL CHECK (
                            target_kind IN (
                                'saturday_lesson', 'sunday_lesson', 'saturday_poll'
                            )
                        ),
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER,
                        sent_at_utc TEXT,
                        status TEXT NOT NULL CHECK (
                            status IN ('pending', 'deleted', 'skipped')
                        ),
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_attempt_at_utc TEXT,
                        failure_category TEXT,
                        failure_notified INTEGER NOT NULL DEFAULT 0,
                        updated_at_utc TEXT NOT NULL,
                        PRIMARY KEY (cleanup_date, target_kind)
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO education_weekend_cleanup_items
                    SELECT cleanup_date, target_kind, chat_id, message_id,
                        sent_at_utc, status, attempts, next_attempt_at_utc,
                        failure_category, failure_notified, updated_at_utc
                    FROM education_weekend_cleanup_items_legacy
                    """
                )
                connection.execute(
                    "DROP TABLE education_weekend_cleanup_items_legacy"
                )

    def ensure_item(
        self,
        *,
        cleanup_date: str,
        target_kind: str,
        chat_id: int,
        message_id: int | None,
        sent_at_utc: str | None,
        now: datetime,
    ) -> None:
        status = "pending" if message_id is not None and sent_at_utc else "skipped"
        failure = None if status == "pending" else "no_verified_sent_message"
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO education_weekend_cleanup_items (
                    cleanup_date, target_kind, chat_id, message_id, sent_at_utc,
                    status, failure_category, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cleanup_date,
                    target_kind,
                    chat_id,
                    message_id,
                    sent_at_utc,
                    status,
                    failure,
                    now.astimezone(timezone.utc).isoformat(),
                ),
            )

    def items(self, cleanup_date: str) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT * FROM education_weekend_cleanup_items
                WHERE cleanup_date = ?
                ORDER BY target_kind
                """,
                (cleanup_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_item(
        self,
        cleanup_date: str,
        target_kind: str,
        *,
        status: str,
        now: datetime,
        failure_category: str | None = None,
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                UPDATE education_weekend_cleanup_items
                SET status = ?, failure_category = ?, next_attempt_at_utc = NULL,
                    updated_at_utc = ?
                WHERE cleanup_date = ? AND target_kind = ?
                """,
                (
                    status,
                    failure_category,
                    now.astimezone(timezone.utc).isoformat(),
                    cleanup_date,
                    target_kind,
                ),
            )

    def record_failure(
        self,
        cleanup_date: str,
        target_kind: str,
        *,
        failure_category: str,
        next_attempt_at: datetime,
        now: datetime,
    ) -> bool:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            row = connection.execute(
                """
                SELECT failure_notified FROM education_weekend_cleanup_items
                WHERE cleanup_date = ? AND target_kind = ?
                """,
                (cleanup_date, target_kind),
            ).fetchone()
            if row is None:
                return False
            should_notify = not bool(row[0])
            connection.execute(
                """
                UPDATE education_weekend_cleanup_items
                SET attempts = attempts + 1, failure_category = ?,
                    next_attempt_at_utc = ?, failure_notified = 1,
                    updated_at_utc = ?
                WHERE cleanup_date = ? AND target_kind = ? AND status = 'pending'
                """,
                (
                    failure_category,
                    next_attempt_at.astimezone(timezone.utc).isoformat(),
                    now.astimezone(timezone.utc).isoformat(),
                    cleanup_date,
                    target_kind,
                ),
            )
        return should_notify

    def due_pending_items(
        self, cleanup_date: str, now: datetime
    ) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT * FROM education_weekend_cleanup_items
                WHERE cleanup_date = ? AND status = 'pending'
                    AND (
                        next_attempt_at_utc IS NULL
                        OR next_attempt_at_utc <= ?
                    )
                ORDER BY target_kind
                """,
                (cleanup_date, now.astimezone(timezone.utc).isoformat()),
            ).fetchall()
        return [dict(row) for row in rows]


class EducationWeekendCleanup:
    """Delete only the tracked Sunday lesson and Saturday group poll."""

    def __init__(
        self,
        api: Any,
        database_path: str | Path,
        *,
        admin_id: int | None,
        education_group_id: int | None,
        morning_store: Any,
        poll_store: Any,
    ) -> None:
        self.api = api
        self.store = EducationWeekendCleanupStore(database_path)
        self.admin_id = admin_id
        self.education_group_id = education_group_id
        self.morning_store = morning_store
        self.poll_store = poll_store

    def dispatch_due(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        local_now = current.astimezone(CLEANUP_ZONE)
        cleanup_date = self._cleanup_date(local_now)
        if cleanup_date is None or self.education_group_id is None:
            return

        cleanup_day = date.fromisoformat(cleanup_date)
        saturday = (cleanup_day - timedelta(days=1)).isoformat()
        saturday_morning = self.morning_store.get(saturday)
        morning = self.morning_store.get(cleanup_date)
        poll = self.poll_store.education_poll_run(f"weekly:{saturday}")

        self.store.ensure_item(
            cleanup_date=cleanup_date,
            target_kind="saturday_lesson",
            chat_id=int(self.education_group_id),
            message_id=self._positive_id(
                saturday_morning.get("telegram_message_id")
                if saturday_morning
                else None
            ),
            sent_at_utc=(
                str(saturday_morning.get("updated_at_utc"))
                if saturday_morning and saturday_morning.get("status") == "sent"
                else None
            ),
            now=current,
        )
        self.store.ensure_item(
            cleanup_date=cleanup_date,
            target_kind="sunday_lesson",
            chat_id=int(self.education_group_id),
            message_id=self._positive_id(
                morning.get("telegram_message_id") if morning else None
            ),
            sent_at_utc=(
                str(morning.get("updated_at_utc"))
                if morning and morning.get("status") == "sent"
                else None
            ),
            now=current,
        )
        self.store.ensure_item(
            cleanup_date=cleanup_date,
            target_kind="saturday_poll",
            chat_id=int(self.education_group_id),
            message_id=self._positive_id(
                poll.get("group_message_id") if poll else None
            ),
            sent_at_utc=(
                str(poll.get("updated_at"))
                if poll and poll.get("group_message_id") is not None
                else None
            ),
            now=current,
        )

        for item in self.store.due_pending_items(cleanup_date, current):
            self._delete_item(cleanup_date, item, current)

    @staticmethod
    def _cleanup_date(local_now: datetime) -> str | None:
        if (
            local_now.weekday() == 6
            and local_now.time().replace(tzinfo=None) >= CLEANUP_TIME
        ):
            return local_now.date().isoformat()
        if local_now.weekday() == 0:
            sunday = local_now.date() - timedelta(days=1)
            scheduled = datetime.combine(sunday, CLEANUP_TIME, tzinfo=CLEANUP_ZONE)
            if local_now - scheduled <= RECOVERY_WINDOW:
                return sunday.isoformat()
        return None

    @staticmethod
    def _positive_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            message_id = int(value)
        except (TypeError, ValueError):
            return None
        return message_id if message_id > 0 else None

    def _delete_item(
        self, cleanup_date: str, item: dict[str, Any], current: datetime
    ) -> None:
        target_kind = str(item["target_kind"])
        sent_at = _as_utc(str(item.get("sent_at_utc") or ""))
        if sent_at is None:
            self._skip(
                cleanup_date,
                target_kind,
                current,
                "send_time_unverified",
            )
            return
        age = current.astimezone(timezone.utc) - sent_at
        if age < timedelta(0) or age >= TELEGRAM_DELETE_WINDOW:
            self._skip(
                cleanup_date,
                target_kind,
                current,
                "telegram_delete_window_expired",
            )
            return

        try:
            deleted = self.api.delete_message(
                int(item["chat_id"]), int(item["message_id"])
            )
            if not deleted:
                raise TelegramAPIError("Telegram did not confirm message deletion.")
        except TelegramAPIError as error:
            message = str(error).casefold()
            if "message to delete not found" in message:
                self.store.update_item(
                    cleanup_date,
                    target_kind,
                    status="deleted",
                    now=current,
                    failure_category="already_absent",
                )
                return
            attempts = int(item.get("attempts") or 0) + 1
            delay_seconds = error.retry_after or min(
                60 * (2 ** min(attempts, 6)), 3600
            )
            should_notify = self.store.record_failure(
                cleanup_date,
                target_kind,
                failure_category=f"telegram_delete_error_{error.error_code or 'unknown'}",
                next_attempt_at=current + timedelta(seconds=delay_seconds),
                now=current,
            )
            if should_notify:
                self._notify_admin(
                    "Weekend cleanup could not remove a tracked Education-group "
                    f"{self._target_label(target_kind)}. Check the bot’s message-"
                    "deletion permission. It will retry while Telegram still "
                    "allows deletion."
                )
            return
        except Exception:
            logger.exception("Unexpected Education-group cleanup error.")
            should_notify = self.store.record_failure(
                cleanup_date,
                target_kind,
                failure_category="unexpected_cleanup_error",
                next_attempt_at=current + timedelta(minutes=5),
                now=current,
            )
            if should_notify:
                self._notify_admin(
                    "Weekend cleanup could not remove a tracked Education-group "
                    f"{self._target_label(target_kind)}. It will retry while "
                    "Telegram still allows deletion."
                )
            return

        self.store.update_item(
            cleanup_date,
            target_kind,
            status="deleted",
            now=current,
        )
        logger.info(
            "Deleted tracked Education-group %s for cleanup date %s.",
            target_kind,
            cleanup_date,
        )

    def _skip(
        self,
        cleanup_date: str,
        target_kind: str,
        now: datetime,
        reason: str,
    ) -> None:
        self.store.update_item(
            cleanup_date,
            target_kind,
            status="skipped",
            failure_category=reason,
            now=now,
        )
        if reason != "no_verified_sent_message":
            self._notify_admin(
                "Weekend cleanup skipped the tracked Education-group "
                f"{self._target_label(target_kind)} because Telegram’s "
                "48-hour deletion window expired or its send time could not "
                "be verified. No other messages were affected."
            )

    @staticmethod
    def _target_label(target_kind: str) -> str:
        return (
            "weekly poll"
            if target_kind == "saturday_poll"
            else "morning lesson"
        )

    def _notify_admin(self, text: str) -> None:
        if self.admin_id is None:
            return
        try:
            self.api.send_message(self.admin_id, text)
        except Exception:
            logger.warning("Could not notify the administrator about cleanup.")
