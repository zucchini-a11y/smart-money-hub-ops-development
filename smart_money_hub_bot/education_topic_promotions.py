"""Guarded one-at-a-time promotions for the Education Market Analysis topic."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import sqlite3
from difflib import SequenceMatcher
from contextlib import contextmanager
from datetime import datetime, time as time_of_day, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .channel_content import validate_channel_post
from .channel_gemini import GeminiChannelGenerationError
from .education_polls import (
    EducationPollError,
    EXPECTED_EDUCATION_GROUP_ID,
    EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
    parse_education_poll_message_link,
)
from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)

REVIEW_WINDOW = timedelta(minutes=5)
DEFAULT_COOLDOWN_DAYS = 14
ALLOWED_COOLDOWNS = {7, 14, 28}
PROMO_SCHEDULE_TIME = time_of_day(19, 0)
PROMO_REVIEW_LEAD = timedelta(minutes=5)
PROMO_REVIEW_LATE_TOLERANCE = timedelta(minutes=1)
PROMO_PUBLISH_GRACE = timedelta(minutes=2)
MAX_PROMO_BODY_CHARS = 700
EXPECTED_BOT_USERNAME = "SmartMoneyHubSignalsBot"
EXPECTED_MARKET_ANALYSIS_THREAD_ID = 5
WAT = ZoneInfo("Africa/Lagos")

_DISALLOWED_PROMO_CLAIMS = re.compile(
    r"\b(?:guarantee(?:d)?\s+(?:profit|profits|returns)|"
    r"risk[\s-]?free\s+(?:profit|trading|returns)|"
    r"100%\s+(?:win(?:ning)?|profit)|"
    r"buy\s+now|sell\s+now|"
    r"we\s+(?:made|earned|won)\s+\$?\d)",
    re.IGNORECASE,
)
_UNSUPPORTED_PROMO_OUTCOMES = re.compile(
    r"\b(?:increase|improve|boost|guarantee)\s+(?:your\s+)?"
    r"(?:win\s*rate|profits?|returns?|earnings?|success)\b|"
    r"\b(?:win\s+more|earn\s+more|make\s+money|profitable\s+trades?)\b",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_MARKET_VALUE_TOPIC = re.compile(
    r"\b(?:levels?|liquidity|market\s+structure|POIs?|FVGs?|fair\s+value\s+gaps?|"
    r"order\s+blocks?|displacement|confirmation)\b",
    re.IGNORECASE,
)
_MARKET_ANALYSIS_CTA = re.compile(
    r"\b(?:tap|open|explore|visit|check\s+out|head\s+to|join)\b"
    r".{0,100}\b(?:market\s+analysis|the\s+button|button\s+below)\b",
    re.IGNORECASE | re.DOTALL,
)
_ZOOM_OR_CLASS = re.compile(r"\b(?:zoom|classes?|class\s+link|class\s+access)\b", re.I)
_WRONG_BREAKDOWN_DESTINATION = re.compile(
    r"\b(?:breakdowns?|breaks\s+down)\b", re.I
)
_UNSUPPORTED_INSTITUTIONAL_PROMO_CLAIMS = re.compile(
    r"\b(?:institutional|institutions?|market\s+makers?|liquidity\s+providers?)\b",
    re.IGNORECASE,
)
_DISALLOWED_PROMO_MARKUP = re.compile(r"(?:\*\*|__|`|<[^>]+>)")
_ZOOM_LINK_ALREADY_AVAILABLE = re.compile(
    r"\b(?:already|now)\s+(?:available|posted|live)\b", re.IGNORECASE
)
_CLASS_LINK_TIMING = re.compile(
    r"\bwhen\s+(?:the\s+)?(?:class|session)\s+(?:begins|starts)\b",
    re.IGNORECASE,
)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(
        tzinfo=timezone.utc
    )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _utc(parsed)


def _url_is_telegram(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc.casefold() == "t.me"
        and bool(parsed.path.strip("/"))
        and not parsed.username
        and not parsed.password
    )


def _body_hash(body: str) -> str:
    normalized = " ".join(body.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class EducationTopicPromotionStore:
    """Persistent state and audit history for explicit group-topic promotions."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS education_topic_promo_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cooldown_days INTEGER NOT NULL DEFAULT 14,
                    next_variant_index INTEGER NOT NULL DEFAULT 0,
                    scheduled_variant_index INTEGER NOT NULL DEFAULT 0,
                    last_published_at TEXT,
                    scheduled_enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO education_topic_promo_settings (id, updated_at)
                VALUES (1, CURRENT_TIMESTAMP);

                CREATE TABLE IF NOT EXISTS education_topic_promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    body TEXT NOT NULL,
                    body_hash TEXT NOT NULL,
                    group_chat_id INTEGER NOT NULL,
                    group_title TEXT NOT NULL,
                    thread_id INTEGER NOT NULL,
                    topic_source_link TEXT NOT NULL,
                    channel_link TEXT NOT NULL,
                    channel_title TEXT NOT NULL,
                    bot_username TEXT NOT NULL,
                    scheduled_for TEXT,
                    schedule_key TEXT,
                    approved_at TEXT,
                    status TEXT NOT NULL CHECK (status IN (
                        'review', 'editing', 'publishing', 'published',
                        'cancelled', 'expired', 'failed',
                        'review_delivery_failed', 'delivery_unknown'
                    )),
                    photo_file_id TEXT,
                    review_started_at TEXT NOT NULL,
                    review_deadline_at TEXT NOT NULL,
                    review_version INTEGER NOT NULL DEFAULT 1,
                    review_sent_at TEXT,
                    edit_admin_id INTEGER,
                    photo_upload_pending INTEGER NOT NULL DEFAULT 0,
                    photo_upload_admin_id INTEGER,
                    publish_attempts INTEGER NOT NULL DEFAULT 0,
                    telegram_message_id INTEGER,
                    published_at TEXT,
                    failure_category TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS education_topic_promo_review
                ON education_topic_promotions (status, review_deadline_at);

                CREATE TABLE IF NOT EXISTS education_topic_promo_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    promotion_id INTEGER REFERENCES education_topic_promotions(id),
                    action TEXT NOT NULL,
                    admin_id INTEGER,
                    details TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS education_topic_promo_schedule_runs (
                    schedule_key TEXT PRIMARY KEY,
                    scheduled_for TEXT NOT NULL,
                    status TEXT NOT NULL,
                    promotion_id INTEGER REFERENCES education_topic_promotions(id),
                    details TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(education_topic_promotions)"
                ).fetchall()
            }
            if "group_title" not in columns:
                connection.execute(
                    """
                    ALTER TABLE education_topic_promotions
                    ADD COLUMN group_title TEXT NOT NULL DEFAULT 'Education group'
                    """
                )
            if "channel_title" not in columns:
                connection.execute(
                    """
                    ALTER TABLE education_topic_promotions
                    ADD COLUMN channel_title TEXT NOT NULL DEFAULT 'Market Analysis channel'
                    """
                )
            if "scheduled_for" not in columns:
                connection.execute(
                    "ALTER TABLE education_topic_promotions ADD COLUMN scheduled_for TEXT"
                )
            if "schedule_key" not in columns:
                connection.execute(
                    "ALTER TABLE education_topic_promotions ADD COLUMN schedule_key TEXT"
                )
            if "approved_at" not in columns:
                connection.execute(
                    "ALTER TABLE education_topic_promotions ADD COLUMN approved_at TEXT"
                )
            settings_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(education_topic_promo_settings)"
                ).fetchall()
            }
            if "scheduled_enabled" not in settings_columns:
                connection.execute(
                    """
                    ALTER TABLE education_topic_promo_settings
                    ADD COLUMN scheduled_enabled INTEGER NOT NULL DEFAULT 1
                    """
                )
            if "scheduled_variant_index" not in settings_columns:
                connection.execute(
                    """
                    ALTER TABLE education_topic_promo_settings
                    ADD COLUMN scheduled_variant_index INTEGER NOT NULL DEFAULT 0
                    """
                )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS education_topic_promo_schedule_key
                ON education_topic_promotions (schedule_key)
                WHERE schedule_key IS NOT NULL
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _action(
        connection: sqlite3.Connection,
        promotion_id: int | None,
        action: str,
        admin_id: int | None,
        details: str,
        at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO education_topic_promo_actions
                (promotion_id, action, admin_id, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (promotion_id, action, admin_id, details[:500], at),
        )

    def settings(self) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM education_topic_promo_settings WHERE id = 1"
            ).fetchone()
            return dict(row) if row else {
                "cooldown_days": DEFAULT_COOLDOWN_DAYS,
                "next_variant_index": 0,
                "scheduled_variant_index": 0,
                "last_published_at": None,
                "scheduled_enabled": 1,
            }

    def set_cooldown(self, days: int, *, admin_id: int, at: str) -> bool:
        if days not in ALLOWED_COOLDOWNS:
            return False
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE education_topic_promo_settings
                SET cooldown_days = ?, updated_at = ? WHERE id = 1
                """,
                (days, at),
            )
            connection.execute(
                """
                INSERT INTO education_topic_promo_actions
                    (promotion_id, action, admin_id, details, created_at)
                VALUES (NULL, 'frequency_changed', ?, ?, ?)
                """,
                (admin_id, f"cooldown_days={days}", at),
            )
        return True

    def set_schedule_enabled(
        self, enabled: bool, *, admin_id: int, at: str
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE education_topic_promo_settings
                SET scheduled_enabled = ?, updated_at = ? WHERE id = 1
                """,
                (int(enabled), at),
            )
            connection.execute(
                """
                INSERT INTO education_topic_promo_actions
                    (promotion_id, action, admin_id, details, created_at)
                VALUES (NULL, 'schedule_enabled_changed', ?, ?, ?)
                """,
                (admin_id, f"enabled={int(enabled)}", at),
            )

    def schedule_run(self, schedule_key: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM education_topic_promo_schedule_runs
                WHERE schedule_key = ?
                """,
                (schedule_key,),
            ).fetchone()
            return dict(row) if row else None

    def record_schedule_event(
        self,
        *,
        schedule_key: str,
        scheduled_for: datetime,
        status: str,
        details: str,
        at: str,
        admin_id: int | None = None,
    ) -> bool:
        if status not in {"missed", "failed", "disabled"}:
            raise ValueError("Unsupported promotion schedule event status.")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO education_topic_promo_schedule_runs
                    (schedule_key, scheduled_for, status, promotion_id, details,
                     created_at, updated_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    schedule_key,
                    _utc(scheduled_for).isoformat(),
                    status,
                    details[:500],
                    at,
                    at,
                ),
            )
            if cursor.rowcount:
                connection.execute(
                    """
                    INSERT INTO education_topic_promo_actions
                        (promotion_id, action, admin_id, details, created_at)
                    VALUES (NULL, ?, ?, ?, ?)
                    """,
                    (
                        f"scheduled_{status}",
                        admin_id,
                        f"schedule_key={schedule_key};{details}"[:500],
                        at,
                    ),
                )
            return bool(cursor.rowcount)

    def create_draft(
        self,
        *,
        body: str,
        group_chat_id: int,
        group_title: str,
        thread_id: int,
        topic_source_link: str,
        channel_link: str,
        channel_title: str,
        bot_username: str,
        admin_id: int,
        now: datetime,
        scheduled_for: datetime | None = None,
        schedule_key: str | None = None,
        generation_model: str | None = None,
        cooldown_override_reason: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        current = _utc(now)
        timestamp = current.isoformat()
        scheduled = _utc(scheduled_for) if scheduled_for else None
        if scheduled is not None and not schedule_key:
            return None, "Scheduled promotions require a unique schedule key."
        deadline = (
            scheduled.isoformat()
            if scheduled
            else (current + REVIEW_WINDOW).isoformat()
        )
        digest = _body_hash(body)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """
                SELECT id FROM education_topic_promotions
                WHERE status IN ('review', 'editing', 'publishing', 'delivery_unknown')
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            if active:
                connection.rollback()
                return None, "An earlier group promotion is still pending or needs delivery verification."
            if schedule_key:
                prior_run = connection.execute(
                    "SELECT status FROM education_topic_promo_schedule_runs WHERE schedule_key = ?",
                    (schedule_key,),
                ).fetchone()
                if prior_run:
                    connection.rollback()
                    return None, "This scheduled promotion has already been handled."
            settings = connection.execute(
                "SELECT * FROM education_topic_promo_settings WHERE id = 1"
            ).fetchone()
            cooldown_days = int(
                settings["cooldown_days"] if settings else DEFAULT_COOLDOWN_DAYS
            )
            last_published = _parse_time(
                str(settings["last_published_at"])
                if settings and settings["last_published_at"]
                else None
            )
            cooldown_override = bool(
                cooldown_override_reason
                and str(cooldown_override_reason).strip()
            )
            if (
                scheduled is None
                and last_published
                and current < last_published + timedelta(days=cooldown_days)
                and not cooldown_override
            ):
                available_at = (last_published + timedelta(days=cooldown_days)).isoformat()
                connection.rollback()
                return None, f"Posting frequency limit reached; another promotion is available after {available_at}."
            if scheduled is None:
                duplicate = connection.execute(
                    """
                    SELECT id FROM education_topic_promotions
                    WHERE status = 'published' AND body_hash = ? LIMIT 1
                    """,
                    (digest,),
                ).fetchone()
            else:
                duplicate = connection.execute(
                    """
                    SELECT id FROM education_topic_promotions
                    WHERE status = 'published' AND body_hash = ?
                        AND published_at >= ?
                    LIMIT 1
                    """,
                    (digest, (current - timedelta(days=180)).isoformat()),
                ).fetchone()
            if duplicate:
                connection.rollback()
                return None, "This promotion wording has already been published. A fresh draft is required."
            cursor = connection.execute(
                """
                INSERT INTO education_topic_promotions (
                    body, body_hash, group_chat_id, group_title, thread_id,
                    topic_source_link, channel_link, channel_title, bot_username,
                    scheduled_for, schedule_key, approved_at, status, review_started_at,
                    review_deadline_at, review_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'review', ?, ?, 1, ?, ?)
                """,
                (
                    body,
                    digest,
                    group_chat_id,
                    group_title,
                    thread_id,
                    topic_source_link,
                    channel_link,
                    channel_title,
                    bot_username,
                    scheduled.isoformat() if scheduled else None,
                    schedule_key,
                    timestamp,
                    deadline,
                    timestamp,
                    timestamp,
                ),
            )
            promotion_id = int(cursor.lastrowid)
            self._action(
                connection,
                promotion_id,
                "draft_created",
                admin_id,
                f"target_chat_id={group_chat_id};thread_id={thread_id};"
                f"generator={generation_model or 'unknown'}",
                timestamp,
            )
            if (
                scheduled is None
                and last_published
                and current < last_published + timedelta(days=cooldown_days)
                and cooldown_override
            ):
                reason = re.sub(
                    r"\s+",
                    " ",
                    str(cooldown_override_reason),
                ).strip()[:200]
                self._action(
                    connection,
                    promotion_id,
                    "owner_requested_cooldown_override",
                    admin_id,
                    f"reason={reason};cooldown_days={cooldown_days}",
                    timestamp,
                )
            if schedule_key and scheduled:
                connection.execute(
                    """
                    INSERT INTO education_topic_promo_schedule_runs
                        (schedule_key, scheduled_for, status, promotion_id,
                         details, created_at, updated_at)
                    VALUES (?, ?, 'review_pending', ?, ?, ?, ?)
                    """,
                    (
                        schedule_key,
                        scheduled.isoformat(),
                        promotion_id,
                        "private review prepared; waiting for scheduled time and final checks",
                        timestamp,
                        timestamp,
                    ),
                )
            row = connection.execute(
                "SELECT * FROM education_topic_promotions WHERE id = ?",
                (promotion_id,),
            ).fetchone()
            connection.commit()
            return dict(row), None
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, promotion_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM education_topic_promotions WHERE id = ?",
                (promotion_id,),
            ).fetchone()
            return dict(row) if row else None

    def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, status, created_at, published_at, failure_category
                FROM education_topic_promotions
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 10)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def recent_captions(self, limit: int = 8) -> list[dict[str, str]]:
        """Return bounded promotion copy only; never include chat or admin identifiers."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT body, status, created_at
                FROM education_topic_promotions
                ORDER BY id DESC LIMIT ?
                """,
                (max(1, min(limit, 8)),),
            ).fetchall()
        return [
            {
                "body": str(row["body"])[:MAX_PROMO_BODY_CHARS],
                "status": str(row["status"])[:24],
                "created_at": str(row["created_at"])[:32],
            }
            for row in rows
        ]

    def has_active_promotion(self) -> bool:
        with self._connection() as connection:
            return connection.execute(
                """
                SELECT 1 FROM education_topic_promotions
                WHERE status IN ('review', 'editing', 'publishing', 'delivery_unknown')
                LIMIT 1
                """
            ).fetchone() is not None

    def record_generation_event(
        self,
        *,
        action: str,
        admin_id: int | None,
        model: str,
        details: str,
        at: str,
    ) -> None:
        safe_action = action if action in {
            "gemini_generation_failed",
            "gemini_generation_rejected",
            "gemini_caption_scope_corrected",
        } else "gemini_generation_failed"
        with self._connection() as connection:
            self._action(
                connection,
                None,
                safe_action,
                admin_id,
                f"model={model[:64]};{details}",
                at,
            )

    def mark_preview_sent(
        self, promotion_id: int, *, admin_id: int, version: int, at: str
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET review_sent_at = ?, updated_at = ?
                WHERE id = ? AND status = 'review' AND review_sent_at IS NULL
                    AND review_version = ?
                """,
                (at, at, promotion_id, version),
            )
            if cursor.rowcount:
                row = connection.execute(
                    """
                    SELECT group_chat_id, thread_id, schedule_key
                    FROM education_topic_promotions WHERE id = ?
                    """,
                    (promotion_id,),
                ).fetchone()
                self._action(
                    connection,
                    promotion_id,
                    "private_preview_sent",
                    admin_id,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']}",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'awaiting_publication', updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (at, row["schedule_key"]),
                    )
            return bool(cursor.rowcount)

    def mark_preview_failed(
        self, promotion_id: int, *, admin_id: int, version: int, at: str
    ) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = 'review_delivery_failed',
                    failure_category = 'admin_preview_delivery_failed',
                    updated_at = ?
                WHERE id = ? AND status = 'review' AND review_version = ?
                """,
                (at, promotion_id, version),
            )
            if cursor.rowcount:
                row = connection.execute(
                    "SELECT schedule_key FROM education_topic_promotions WHERE id = ?",
                    (promotion_id,),
                ).fetchone()
                if row and row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'failed', details = 'private preview delivery failed',
                            updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (at, row["schedule_key"]),
                    )
                self._action(
                    connection,
                    promotion_id,
                    "private_preview_failed",
                    admin_id,
                    "group destination was not contacted",
                    at,
                )

    def begin_edit(
        self, promotion_id: int, *, admin_id: int, version: int, at: str
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = 'editing', edit_admin_id = ?, updated_at = ?
                WHERE id = ? AND status = 'review' AND review_sent_at IS NOT NULL
                    AND review_deadline_at > ? AND review_version = ?
                """,
                (admin_id, at, promotion_id, at, version),
            )
            if cursor.rowcount:
                self._action(connection, promotion_id, "edit_started", admin_id, "", at)
            return bool(cursor.rowcount)

    def has_edit_pending(self, admin_id: int, *, at: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM education_topic_promotions
                WHERE status = 'editing' AND edit_admin_id = ?
                    AND review_deadline_at > ?
                ORDER BY id DESC LIMIT 1
                """,
                (admin_id, at),
            ).fetchone()
            return row is not None

    def save_edit(
        self, promotion_id: int, body: str, *, admin_id: int, now: datetime
    ) -> bool:
        current = _utc(now)
        timestamp = current.isoformat()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT scheduled_for, schedule_key FROM education_topic_promotions WHERE id = ?",
                (promotion_id,),
            ).fetchone()
            if not existing:
                return False
            next_deadline = (
                str(existing["scheduled_for"])
                if existing["scheduled_for"]
                else (current + REVIEW_WINDOW).isoformat()
            )
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET body = ?, body_hash = ?, status = 'review', edit_admin_id = NULL,
                    review_started_at = ?, review_deadline_at = ?, review_sent_at = NULL,
                    review_version = review_version + 1,
                    photo_upload_pending = 0, photo_upload_admin_id = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'editing' AND edit_admin_id = ?
                    AND review_deadline_at > ?
                """,
                (
                    body,
                    _body_hash(body),
                    timestamp,
                    next_deadline,
                    timestamp,
                    promotion_id,
                    admin_id,
                    timestamp,
                ),
            )
            if cursor.rowcount:
                self._action(connection, promotion_id, "caption_edited", admin_id, "", timestamp)
            return bool(cursor.rowcount)

    def request_photo(
        self, promotion_id: int, *, admin_id: int, version: int, at: str
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET photo_upload_pending = 1, photo_upload_admin_id = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'review' AND review_sent_at IS NOT NULL
                    AND review_deadline_at > ? AND review_version = ?
                    AND approved_at IS NULL AND publish_attempts = 0
                """,
                (admin_id, at, promotion_id, at, version),
            )
            if cursor.rowcount:
                self._action(
                    connection, promotion_id, "photo_requested", admin_id, "", at
                )
            return bool(cursor.rowcount)

    def pending_photo(self, admin_id: int, *, at: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM education_topic_promotions
                WHERE photo_upload_pending = 1 AND photo_upload_admin_id = ?
                    AND status = 'review' AND review_deadline_at > ?
                ORDER BY id DESC LIMIT 1
                """,
                (admin_id, at),
            ).fetchone()
            return dict(row) if row else None

    def has_input_pending(self, admin_id: int, *, at: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM education_topic_promotions
                WHERE status IN ('editing', 'review') AND review_deadline_at > ?
                    AND (edit_admin_id = ? OR photo_upload_admin_id = ?)
                ORDER BY id DESC LIMIT 1
                """,
                (at, admin_id, admin_id),
            ).fetchone()
            return row is not None

    def editing_for_admin(self, admin_id: int, *, at: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM education_topic_promotions
                WHERE status = 'editing' AND edit_admin_id = ?
                    AND review_deadline_at > ?
                ORDER BY id DESC LIMIT 1
                """,
                (admin_id, at),
            ).fetchone()
            return dict(row) if row else None

    def cancellable_input_for_admin(self, admin_id: int, *, at: str) -> int | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id FROM education_topic_promotions
                WHERE status IN ('editing', 'review')
                    AND (edit_admin_id = ? OR photo_upload_admin_id = ?)
                    AND review_deadline_at > ?
                ORDER BY id DESC LIMIT 1
                """,
                (admin_id, admin_id, at),
            ).fetchone()
            return int(row["id"]) if row else None

    def attach_photo(
        self, promotion_id: int, file_id: str, *, admin_id: int, now: datetime
    ) -> bool:
        current = _utc(now)
        timestamp = current.isoformat()
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT scheduled_for FROM education_topic_promotions WHERE id = ?",
                (promotion_id,),
            ).fetchone()
            if not existing:
                return False
            next_deadline = (
                str(existing["scheduled_for"])
                if existing["scheduled_for"]
                else (current + REVIEW_WINDOW).isoformat()
            )
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET photo_file_id = ?, photo_upload_pending = 0,
                    photo_upload_admin_id = NULL, review_started_at = ?,
                    review_deadline_at = ?, review_sent_at = NULL,
                    review_version = review_version + 1, approved_at = NULL,
                    updated_at = ?
                WHERE id = ? AND photo_upload_pending = 1
                    AND photo_upload_admin_id = ? AND status = 'review'
                    AND review_deadline_at > ? AND publish_attempts = 0
                """,
                (
                    file_id,
                    timestamp,
                    next_deadline,
                    timestamp,
                    promotion_id,
                    admin_id,
                    timestamp,
                ),
            )
            if cursor.rowcount:
                self._action(connection, promotion_id, "photo_attached", admin_id, "", timestamp)
                schedule = connection.execute(
                    "SELECT schedule_key FROM education_topic_promotions WHERE id = ?",
                    (promotion_id,),
                ).fetchone()
                if schedule and schedule["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'review_pending',
                            details = 'photo added; updated preview awaits approval',
                            updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (timestamp, schedule["schedule_key"]),
                    )
            return bool(cursor.rowcount)

    def cancel(
        self, promotion_id: int, *, admin_id: int, version: int | None, at: str
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = 'cancelled', photo_upload_pending = 0,
                    photo_upload_admin_id = NULL, edit_admin_id = NULL,
                    updated_at = ?
                WHERE id = ? AND status IN ('review', 'editing')
                    AND review_deadline_at > ?
                    AND (? IS NULL OR review_version = ?)
                """,
                (at, promotion_id, at, version, version),
            )
            if cursor.rowcount:
                self._action(connection, promotion_id, "cancelled", admin_id, "", at)
                row = connection.execute(
                    "SELECT schedule_key FROM education_topic_promotions WHERE id = ?",
                    (promotion_id,),
                ).fetchone()
                if row and row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'cancelled', details = 'admin cancelled the preview',
                            updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (at, row["schedule_key"]),
                    )
            return bool(cursor.rowcount)

    def claim_publish(
        self,
        promotion_id: int,
        *,
        admin_id: int,
        version: int,
        at: str,
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = 'publishing', publish_attempts = publish_attempts + 1,
                    photo_upload_pending = 0, photo_upload_admin_id = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'review' AND review_sent_at IS NOT NULL
                    AND review_deadline_at > ? AND publish_attempts = 0
                    AND review_version = ?
                """,
                (at, promotion_id, at, version),
            )
            if cursor.rowcount:
                row = connection.execute(
                    """
                    SELECT group_chat_id, thread_id, schedule_key
                    FROM education_topic_promotions WHERE id = ?
                    """,
                    (promotion_id,),
                ).fetchone()
                self._action(
                    connection,
                    promotion_id,
                    "explicit_approval_and_publish_started",
                    admin_id,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']}",
                    at,
                )
            return bool(cursor.rowcount)

    def approve_scheduled(
        self,
        promotion_id: int,
        *,
        admin_id: int,
        version: int,
        at: str,
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET approved_at = ?, updated_at = ?
                WHERE id = ? AND status = 'review' AND scheduled_for IS NOT NULL
                    AND review_sent_at IS NOT NULL AND review_deadline_at > ?
                    AND approved_at IS NULL AND publish_attempts = 0
                    AND review_version = ?
                """,
                (at, at, promotion_id, at, version),
            )
            if cursor.rowcount:
                row = connection.execute(
                    """
                    SELECT group_chat_id, thread_id, schedule_key, scheduled_for
                    FROM education_topic_promotions WHERE id = ?
                    """,
                    (promotion_id,),
                ).fetchone()
                self._action(
                    connection,
                    promotion_id,
                    "scheduled_post_approved",
                    admin_id,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']};"
                    f"scheduled_for={row['scheduled_for']}",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'approved', updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (at, row["schedule_key"]),
                    )
            return bool(cursor.rowcount)

    def scheduled_posts_due(self, *, at: str) -> list[dict[str, Any]]:
        current = _parse_time(at)
        if current is None:
            return []
        oldest = (current - PROMO_PUBLISH_GRACE).isoformat()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM education_topic_promotions
                WHERE status = 'review' AND scheduled_for IS NOT NULL
                    AND review_sent_at IS NOT NULL
                    AND publish_attempts = 0 AND scheduled_for <= ?
                    AND scheduled_for >= ?
                ORDER BY scheduled_for, id
                """,
                (at, oldest),
            ).fetchall()
            return [dict(row) for row in rows]

    def claim_scheduled_publish(
        self,
        promotion_id: int,
        *,
        admin_id: int,
        version: int,
        at: str,
    ) -> bool:
        current = _parse_time(at)
        if current is None:
            return False
        oldest = (current - PROMO_PUBLISH_GRACE).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = 'publishing', publish_attempts = publish_attempts + 1,
                    photo_upload_pending = 0, photo_upload_admin_id = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'review' AND scheduled_for IS NOT NULL
                    AND scheduled_for <= ? AND scheduled_for >= ?
                    AND review_sent_at IS NOT NULL
                    AND publish_attempts = 0 AND review_version = ?
                """,
                (at, promotion_id, at, oldest, version),
            )
            if cursor.rowcount:
                row = connection.execute(
                    "SELECT group_chat_id, thread_id, schedule_key FROM education_topic_promotions WHERE id = ?",
                    (promotion_id,),
                ).fetchone()
                self._action(
                    connection,
                    promotion_id,
                    "scheduled_auto_publish_started",
                    admin_id,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']}",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'publishing', updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (at, row["schedule_key"]),
                    )
            return bool(cursor.rowcount)

    def fail_scheduled_review(
        self,
        promotion_id: int,
        *,
        admin_id: int | None,
        category: str,
        at: str,
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = 'failed', failure_category = ?, updated_at = ?
                WHERE id = ? AND status IN ('review', 'editing')
                    AND scheduled_for IS NOT NULL
                """,
                (category[:100], at, promotion_id),
            )
            if cursor.rowcount:
                row = connection.execute(
                    "SELECT group_chat_id, thread_id, schedule_key FROM education_topic_promotions WHERE id = ?",
                    (promotion_id,),
                ).fetchone()
                details = (
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']};"
                    f"category={category[:100]}"
                )
                self._action(
                    connection,
                    promotion_id,
                    "scheduled_publish_held",
                    admin_id,
                    details,
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'failed', details = ?, updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (category[:500], at, row["schedule_key"]),
                    )
            return bool(cursor.rowcount)

    def finish_publish(
        self, promotion_id: int, message_id: int, *, admin_id: int, at: str
    ) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = 'published', telegram_message_id = ?,
                    published_at = ?, failure_category = NULL, updated_at = ?
                WHERE id = ? AND status = 'publishing' AND publish_attempts = 1
                """,
                (message_id, at, at, promotion_id),
            )
            if cursor.rowcount:
                connection.execute(
                    """
                    UPDATE education_topic_promo_settings
                    SET last_published_at = ?, updated_at = ? WHERE id = 1
                    """,
                    (at, at),
                )
                row = connection.execute(
                    """
                    SELECT group_chat_id, thread_id, schedule_key
                    FROM education_topic_promotions WHERE id = ?
                    """,
                    (promotion_id,),
                ).fetchone()
                self._action(
                    connection,
                    promotion_id,
                    "published",
                    admin_id,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']};message_id={message_id}",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'published', details = ?, updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (
                            f"telegram_message_id={message_id}",
                            at,
                            row["schedule_key"],
                        ),
                    )
            return bool(cursor.rowcount)

    def fail_publish(
        self,
        promotion_id: int,
        *,
        admin_id: int,
        category: str,
        delivery_unknown: bool,
        at: str,
    ) -> None:
        status = "delivery_unknown" if delivery_unknown else "failed"
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET status = ?, failure_category = ?, updated_at = ?
                WHERE id = ? AND status = 'publishing'
                """,
                (status, category[:100], at, promotion_id),
            )
            if cursor.rowcount:
                row = connection.execute(
                    """
                    SELECT group_chat_id, thread_id, schedule_key
                    FROM education_topic_promotions WHERE id = ?
                    """,
                    (promotion_id,),
                ).fetchone()
                self._action(
                    connection,
                    promotion_id,
                    status,
                    admin_id,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']};category={category[:100]}",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = ?, details = ?, updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (
                            status,
                            category[:500],
                            at,
                            row["schedule_key"],
                        ),
                    )

    def expire_due(self, *, at: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, group_chat_id, thread_id, schedule_key,
                       approved_at, scheduled_for
                FROM education_topic_promotions
                WHERE status IN ('review', 'editing') AND review_deadline_at <= ?
                """,
                (at,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE education_topic_promotions
                    SET status = 'expired',
                        failure_category = CASE
                            WHEN scheduled_for IS NOT NULL THEN 'scheduled_publish_window_missed'
                            WHEN approved_at IS NOT NULL THEN 'approved_schedule_missed'
                            ELSE 'approval_window_expired'
                        END,
                        photo_upload_pending = 0,
                        photo_upload_admin_id = NULL, edit_admin_id = NULL,
                        updated_at = ?
                    WHERE id = ? AND status IN ('review', 'editing')
                    """,
                    (at, row["id"]),
                )
                self._action(
                    connection,
                    int(row["id"]),
                    "review_expired_no_post",
                    None,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']}",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'expired',
                            details = CASE
                                WHEN ? IS NOT NULL THEN 'scheduled post missed its publication window'
                                WHEN ? IS NOT NULL THEN 'approved post missed its scheduled window'
                                ELSE 'approval window expired'
                            END,
                            updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (
                            row["scheduled_for"],
                            row["approved_at"],
                            at,
                            row["schedule_key"],
                        ),
                    )
            return [dict(row) for row in rows]

    def recover_interrupted(self, *, at: str) -> list[dict[str, Any]]:
        """Close interrupted sends as uncertain so they can never auto-retry."""
        recovered: list[dict[str, Any]] = []
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            publishing = connection.execute(
                """
                SELECT id, group_chat_id, thread_id, schedule_key
                FROM education_topic_promotions WHERE status = 'publishing'
                """
            ).fetchall()
            for row in publishing:
                connection.execute(
                    """
                    UPDATE education_topic_promotions
                    SET status = 'delivery_unknown',
                        failure_category = 'process_interrupted_during_send',
                        updated_at = ?
                    WHERE id = ? AND status = 'publishing'
                    """,
                    (at, row["id"]),
                )
                self._action(
                    connection,
                    int(row["id"]),
                    "restart_delivery_unknown",
                    None,
                    f"target_chat_id={row['group_chat_id']};thread_id={row['thread_id']}",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'delivery_unknown',
                            details = 'process interrupted during send',
                            updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (at, row["schedule_key"]),
                    )
                recovered.append(
                    {"id": int(row["id"]), "status": "delivery_unknown"}
                )
            unsent_previews = connection.execute(
                """
                SELECT id, group_chat_id, thread_id, schedule_key
                FROM education_topic_promotions
                WHERE status = 'review' AND review_sent_at IS NULL
                """
            ).fetchall()
            for row in unsent_previews:
                connection.execute(
                    """
                    UPDATE education_topic_promotions
                    SET status = 'review_delivery_failed',
                        failure_category = 'process_interrupted_before_preview_confirmation',
                        updated_at = ?
                    WHERE id = ? AND status = 'review' AND review_sent_at IS NULL
                    """,
                    (at, row["id"]),
                )
                self._action(
                    connection,
                    int(row["id"]),
                    "restart_preview_unconfirmed",
                    None,
                    "No member destination was contacted",
                    at,
                )
                if row["schedule_key"]:
                    connection.execute(
                        """
                        UPDATE education_topic_promo_schedule_runs
                        SET status = 'failed',
                            details = 'process restarted before preview was confirmed',
                            updated_at = ?
                        WHERE schedule_key = ?
                        """,
                        (at, row["schedule_key"]),
                    )
                recovered.append(
                    {"id": int(row["id"]), "status": "review_delivery_failed"}
                )
        return recovered


class EducationTopicPromotionManager:
    """Create private promotional reviews and publish only on explicit approval."""

    def __init__(
        self,
        api: TelegramAPI,
        database_path: str | Path,
        *,
        admin_id: int | None,
        education_group_id: int | None,
        market_channel_id: int | None,
        topic_message_link: str | None,
        writer: Any | None = None,
    ) -> None:
        self.api = api
        self.writer = writer
        self.admin_id = admin_id
        self.education_group_id = education_group_id
        self.market_channel_id = market_channel_id
        self.topic_message_link = (topic_message_link or "").strip()
        self.store = EducationTopicPromotionStore(database_path)
        self._recovery_checked = False
        self.thread_id: int | None = None
        self.topic_config_error: str | None = None
        try:
            group_id, thread_id, _message_id = parse_education_poll_message_link(
                self.topic_message_link
            )
            if thread_id is None:
                raise ValueError("The topic link does not contain a forum thread ID.")
            if group_id != education_group_id or group_id != EXPECTED_EDUCATION_GROUP_ID:
                raise ValueError("The topic link does not match the configured Education group.")
            if thread_id != EXPECTED_MARKET_ANALYSIS_THREAD_ID:
                raise ValueError("The configured link is not the approved Market Analysis topic.")
            self.thread_id = thread_id
        except (EducationPollError, TypeError, ValueError) as error:
            detail = (
                str(error)
                if isinstance(error, ValueError)
                else "The configured link could not be parsed."
            )
            self.topic_config_error = (
                f"The configured Market Analysis topic link is invalid: {detail} "
                "No group post can be prepared until the correct topic-specific "
                "Telegram link is configured."
            )

    def has_edit_pending(self, admin_id: int, *, now: datetime | None = None) -> bool:
        current = _utc(now or datetime.now(timezone.utc))
        return (
            self.admin_id is not None
            and admin_id == self.admin_id
            and self.store.has_edit_pending(admin_id, at=current.isoformat())
        )

    def has_input_pending(self, admin_id: int, *, now: datetime | None = None) -> bool:
        current = _utc(now or datetime.now(timezone.utc))
        return (
            self.admin_id is not None
            and admin_id == self.admin_id
            and self.store.has_input_pending(admin_id, at=current.isoformat())
        )

    def _authorized(self, chat_id: int, admin_id: int, is_private: bool) -> bool:
        return (
            is_private
            and self.admin_id is not None
            and admin_id == self.admin_id
            and chat_id == self.admin_id
        )

    def _verify_targets(self) -> tuple[str, str, str, str, str]:
        if self.topic_config_error:
            raise ValueError(self.topic_config_error)
        if (
            self.education_group_id != EXPECTED_EDUCATION_GROUP_ID
            or self.market_channel_id != EXPECTED_MARKET_ANALYSIS_CHANNEL_ID
            or self.thread_id is None
        ):
            raise ValueError("The Education group, Market Analysis channel, or topic is not configured.")
        try:
            group = self.api.get_chat(self.education_group_id)
            bot = self.api.get_me()
            group_member = self.api.get_chat_member(
                self.education_group_id, int(bot["id"])
            )
            channel = self.api.get_chat(self.market_channel_id)
            channel_member = self.api.get_chat_member(
                self.market_channel_id, int(bot["id"])
            )
        except (TelegramAPIError, KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Telegram could not verify the group, channel, or bot permissions."
            ) from error

        if (
            group.get("id") != self.education_group_id
            or group.get("type") != "supergroup"
            or group.get("is_forum") is not True
            or group_member.get("status") not in {"administrator", "creator"}
            or group_member.get("can_manage_topics") is not True
        ):
            raise ValueError(
                "The configured Education destination is not verified as the "
                "forum group with bot topic-management access."
            )
        if (
            channel.get("id") != self.market_channel_id
            or channel.get("type") != "channel"
            or channel_member.get("status") not in {"administrator", "creator"}
            or (
                channel_member.get("status") != "creator"
                and channel_member.get("can_post_messages") is not True
            )
        ):
            raise ValueError(
                "The configured Market Analysis channel or bot posting permission "
                "could not be verified."
            )
        username = bot.get("username")
        if username != EXPECTED_BOT_USERNAME:
            raise ValueError("Telegram did not confirm the expected Smart Money Hub bot username.")
        channel_url = channel.get("username")
        if isinstance(channel_url, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", channel_url):
            channel_link = f"https://t.me/{channel_url}"
        else:
            channel_link = channel.get("invite_link")
        if not isinstance(channel_link, str) or not _url_is_telegram(channel_link):
            raise ValueError(
                "Telegram did not provide a usable Market Analysis channel link. "
                "No link was invented."
            )
        group_title = group.get("title")
        channel_title = channel.get("title")
        if not isinstance(group_title, str) or not group_title.strip():
            raise ValueError("Telegram did not confirm the Education group name.")
        if not isinstance(channel_title, str) or not channel_title.strip():
            raise ValueError("Telegram did not confirm the Market Analysis channel name.")
        return (
            channel_link,
            f"https://t.me/{username}",
            username,
            group_title.strip(),
            channel_title.strip(),
        )

    @staticmethod
    def _validate_body(
        body: str, *, promotion_type: str = "manual"
    ) -> str | None:
        text = " ".join(body.split())
        if not text or len(text) > MAX_PROMO_BODY_CHARS:
            return f"Caption must be 1–{MAX_PROMO_BODY_CHARS} characters."
        if _URL.search(text):
            return "Keep links in the verified buttons; remove URLs from the caption."
        if _DISALLOWED_PROMO_CLAIMS.search(text):
            return "The caption contains a trading result, guaranteed claim, or direct signal."
        if _UNSUPPORTED_PROMO_OUTCOMES.search(text):
            return "Do not promise profits, win rates, earnings, or trading results."
        if _UNSUPPORTED_INSTITUTIONAL_PROMO_CLAIMS.search(text):
            return (
                "Remove unverified claims about institutional activity, market "
                "makers, or liquidity providers."
            )
        folded = text.casefold()
        if "market analysis" not in folded or not re.search(
            r"\b(?:gold|xau\s*/?\s*usd)\b", folded
        ):
            return (
                "The promotion must focus on the separate Market Analysis channel "
                "and its Gold/USD educational coverage."
            )
        if not _MARKET_VALUE_TOPIC.search(text):
            return (
                "Explain at least one relevant educational market concept, such as "
                "structure, liquidity, levels, POIs, FVGs, or confirmation."
            )
        if not _MARKET_ANALYSIS_CTA.search(text):
            return (
                "Add a clear primary call to action directing readers to the "
                "Open Market Analysis button."
            )
        if _WRONG_BREAKDOWN_DESTINATION.search(text):
            return (
                "Remove references to features outside this channel; describe only "
                "its verified Gold/USD educational coverage."
            )
        if re.search(r"\b(?:coach|assistant|bot|pro signals?)\b", folded):
            return (
                "Keep the caption focused on the separate Market Analysis channel; "
                "the Coach button remains available separately."
            )

        class_paragraphs = [
            paragraph
            for paragraph in (part.strip() for part in body.split("\n\n"))
            if paragraph and _ZOOM_OR_CLASS.search(paragraph)
        ]
        if class_paragraphs:
            if promotion_type != "scheduled_class":
                return "Only a scheduled class promotion may include the optional Zoom reminder."
            if len(class_paragraphs) > 1:
                return "Keep any Zoom reminder to one short, secondary paragraph."
            class_line = class_paragraphs[0]
            if _ZOOM_LINK_ALREADY_AVAILABLE.search(class_line):
                return "Do not say the Zoom link is already available."
            if "monday" not in class_line.casefold() or "thursday" not in class_line.casefold():
                return "A Zoom reminder must use the configured Monday and Thursday schedule."
            if not re.search(r"\b8(?::00)?\s*pm\s*wat\b", class_line, re.IGNORECASE):
                return "A Zoom reminder must use the configured 8:00 PM WAT class time."
            if "main smart money hub channel" not in class_line.casefold():
                return (
                    "Say that class access is shared in the main Smart Money Hub "
                    "channel, not the Education Group."
                )
            if not _CLASS_LINK_TIMING.search(class_line):
                return "Say the class link is posted when the class or session begins."
            if "education group" in class_line.casefold():
                return "Never direct members to the Education Group for the Zoom link."
            cta = _MARKET_ANALYSIS_CTA.search(body)
            if cta is None or body.rfind(class_line) < cta.end():
                return "Keep the optional Zoom reminder after the Market Analysis call to action."

        safety_issue = validate_channel_post(
            body.strip(),
            is_promo=False,
            require_golden_rule=False,
        )
        if safety_issue:
            return f"The caption failed the existing content-safety check ({safety_issue})."
        return None

    @classmethod
    def _validate_generated_body(
        cls,
        body: str,
        *,
        recent_captions: list[dict[str, str]],
        promotion_type: str,
        weekday: str | None,
    ) -> str | None:
        text = body.strip()
        if not text:
            return "Gemini returned an empty promotion caption."
        if len(text) < 180:
            return (
                f"Gemini caption is too short ({len(text)} characters; minimum 180)."
            )
        if len(text) > MAX_PROMO_BODY_CHARS:
            return (
                f"Gemini caption is too long ({len(text)} characters; maximum "
                f"{MAX_PROMO_BODY_CHARS})."
            )
        if _URL.search(text) or _DISALLOWED_PROMO_MARKUP.search(text):
            return "Gemini's caption must be plain text without raw links or markup."
        lines = [line.strip() for line in body.strip().splitlines() if line.strip()]
        headline = lines[0]
        if len(headline) > 100 or not any(char.isalpha() for char in headline):
            return "Gemini's caption needs a short, relevant headline."
        if not headline.startswith(
            ("📊", "🥇", "🪙", "💧", "🎯", "🧠", "📈", "🔍", "📚", "🌍", "🧭")
        ):
            return "Start the headline with a relevant market or Gold emoji."
        body_issue = cls._validate_body(text, promotion_type=promotion_type)
        if body_issue:
            return body_issue

        for item in recent_captions:
            prior = str(item.get("body") or "").strip()
            prior_lines = [line.strip() for line in prior.splitlines() if line.strip()]
            if not prior_lines:
                continue
            current_core = cls._novelty_core(body)
            prior_core = cls._novelty_core(prior)
            if (
                len(current_core) >= 45
                and len(prior_core) >= 45
                and SequenceMatcher(None, current_core, prior_core).ratio() >= 0.82
            ):
                return "The caption is too similar to a recent promotion; write a new angle."
        return None

    @staticmethod
    def _novelty_core(text: str) -> str:
        lines = []
        for line in text.splitlines():
            lowered = line.casefold()
            if any(
                marker in lowered
                for marker in (
                    "open market analysis button",
                    "separate market analysis channel",
                    "no confirmation, no entry",
                )
            ):
                continue
            lines.append(line)
        return " ".join(re.sub(r"[^\w\s]", " ", " ".join(lines).casefold()).split())

    @staticmethod
    def _remove_out_of_scope_sentences(body: str) -> tuple[str, bool]:
        """Remove sentences advertising content that belongs to another destination."""
        changed = False
        paragraphs: list[str] = []
        for paragraph in re.split(r"\n\s*\n", body.strip()):
            fragments = re.split(r"(?<=[.!?])\s+", paragraph.strip())
            kept: list[str] = []
            for fragment in fragments:
                cleaned = fragment.strip()
                if not cleaned:
                    continue
                if _WRONG_BREAKDOWN_DESTINATION.search(cleaned):
                    changed = True
                    continue
                kept.append(cleaned)
            if kept:
                paragraphs.append(" ".join(kept))
        return "\n\n".join(paragraphs), changed

    def _generate_body(
        self,
        *,
        now: datetime,
        promotion_type: str,
        weekday: str | None = None,
    ) -> tuple[str | None, str | None]:
        if self.writer is None or not callable(
            getattr(self.writer, "generate_promotion", None)
        ):
            self.store.record_generation_event(
                action="gemini_generation_failed",
                admin_id=self.admin_id,
                model="gemini-3.5-flash-lite",
                details=f"type={promotion_type};category=gemini_not_configured",
                at=_utc(now).isoformat(),
            )
            return None, "Gemini is not configured for promotions. No draft was created."

        history = self.store.recent_captions()
        prompt_history = [
            item
            for item in history
            if "breakdown" not in str(item.get("body") or "").casefold()
        ]
        model = str(getattr(self.writer, "model", "gemini-3.5-flash-lite"))
        retry_feedback: str | None = None
        last_issue: str | None = None
        retryable_generation_errors = {
            "gemini_invalid_response",
            "gemini_missing_candidate",
            "gemini_invalid_candidate",
            "gemini_missing_text",
            "gemini_missing_category",
            "gemini_missing_post",
        }
        for attempt in range(1, 3):
            try:
                body = self.writer.generate_promotion(
                    recent_captions=prompt_history,
                    promotion_type=promotion_type,
                    weekday=weekday,
                    retry_feedback=retry_feedback,
                )
            except GeminiChannelGenerationError as error:
                logger.warning(
                    "Education-topic Gemini promotion generation failed model=%s "
                    "category=%s attempt=%s http_status=%s.",
                    model,
                    error.category,
                    attempt,
                    error.http_status,
                )
                if attempt == 1 and error.category in retryable_generation_errors:
                    retry_feedback = (
                        "The previous response was empty or malformed. Return one "
                        "complete promotion caption with no labels or explanation."
                    )
                    continue
                self.store.record_generation_event(
                    action="gemini_generation_failed",
                    admin_id=self.admin_id,
                    model=model,
                    details=(
                        f"type={promotion_type};category={error.category};"
                        f"http_status={error.http_status or 'none'};attempt={attempt}"
                    ),
                    at=_utc(now).isoformat(),
                )
                return None, self._generation_error_message(error)
            except Exception as error:
                logger.error(
                    "Education-topic Gemini promotion writer failed model=%s "
                    "exception_type=%s attempt=%s.",
                    model,
                    type(error).__name__,
                    attempt,
                )
                self.store.record_generation_event(
                    action="gemini_generation_failed",
                    admin_id=self.admin_id,
                    model=model,
                    details=f"type={promotion_type};category=unexpected_writer_error",
                    at=_utc(now).isoformat(),
                )
                return None, "Gemini could not prepare the promotion. No draft was created."

            candidate, scope_corrected = self._remove_out_of_scope_sentences(
                str(body or "")
            )
            if scope_corrected:
                self.store.record_generation_event(
                    action="gemini_caption_scope_corrected",
                    admin_id=self.admin_id,
                    model=model,
                    details=(
                        f"type={promotion_type};attempt={attempt};"
                        "removed_out_of_scope_sentence;full_validation_rerun"
                    ),
                    at=_utc(now).isoformat(),
                )
            issue = self._validate_generated_body(
                candidate,
                recent_captions=history,
                promotion_type=promotion_type,
                weekday=weekday,
            )
            if issue is None:
                return candidate.strip(), None
            last_issue = issue
            self.store.record_generation_event(
                action="gemini_generation_rejected",
                admin_id=self.admin_id,
                model=model,
                details=f"type={promotion_type};attempt={attempt};reason={issue}",
                at=_utc(now).isoformat(),
            )
            if attempt == 1:
                issue_lower = issue.casefold()
                if "too short" in issue_lower or "too long" in issue_lower:
                    retry_feedback = (
                        "The caption failed the length check. Return one complete "
                        "plain-text caption between 280 and 500 characters inclusive. "
                        "Count spaces and punctuation; do not return an explanation."
                    )
                elif "breakdown" in issue_lower:
                    retry_feedback = (
                        "Keep the caption strictly within the verified Gold/USD "
                        "Market Analysis channel scope. Omit unrelated feature claims."
                    )
                else:
                    retry_feedback = (
                        f"The previous response failed this check: {issue} "
                        "Return a materially different, corrected, complete promotion "
                        "caption. Follow all destination, class, and safety rules."
                    )
        return None, (
            "Gemini's caption failed content checks after two attempts. "
            "No draft was saved. Last issue: "
            f"{last_issue or 'content validation failed'}"
        )

    @staticmethod
    def _generation_error_message(error: GeminiChannelGenerationError) -> str:
        if error.category == "gemini_not_configured":
            return "Gemini is not configured. No draft was created."
        if error.category == "gemini_rate_limit":
            return "Gemini is rate-limited right now. No draft was created; try again later."
        if error.category == "gemini_timeout":
            return "Gemini timed out. No draft was created."
        if error.category == "gemini_network_error":
            return "Gemini could not be reached. No draft was created."
        if error.http_status:
            return (
                f"Gemini returned HTTP {error.http_status}. "
                "No draft was created; check the model service and try again."
            )
        return (
            f"Gemini returned an unusable response ({error.category}). "
            "No draft was created."
        )

    @staticmethod
    def _render(body: str) -> str:
        return (
            "📊 <b>SMART MONEY HUB | MARKET ANALYSIS CHANNEL</b>\n\n"
            f"{html.escape(body, quote=False)}\n\n"
            "For educational purposes only. Trading involves risk."
        )

    @staticmethod
    def _member_keyboard(channel_link: str, bot_link: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": "📊 Open Market Analysis", "url": channel_link}],
                [{"text": "Coach", "url": bot_link}],
            ]
        }

    def _review_keyboard(self, promotion: dict[str, Any]) -> dict[str, Any]:
        version = int(promotion["review_version"])
        promotion_id = int(promotion["id"])
        links = self._member_keyboard(
            str(promotion["channel_link"]),
            f"https://t.me/{promotion['bot_username']}",
        )["inline_keyboard"]
        scheduled_for = _parse_time(str(promotion["scheduled_for"])) if promotion.get("scheduled_for") else None
        edit_and_cancel = [
            {
                "text": "✏️ Edit Caption",
                "callback_data": f"admin:education_topic_promo:edit:{promotion_id}:{version}",
            },
            {
                "text": "Cancel",
                "callback_data": f"admin:education_topic_promo:cancel:{promotion_id}:{version}",
            },
        ]
        add_photo = {
            "text": "🖼 Add Picture",
            "callback_data": f"admin:education_topic_promo:photo:{promotion_id}:{version}",
        }
        if scheduled_for:
            return {"inline_keyboard": [*links, edit_and_cancel, [add_photo]]}
        approve_label = (
            f"✅ Approve for {scheduled_for.astimezone(WAT).strftime('%H:%M WAT')}"
            if scheduled_for
            else "✅ Approve & Publish"
        )
        return {
            "inline_keyboard": [
                *links,
                [
                    {
                        "text": approve_label,
                        "callback_data": f"admin:education_topic_promo:approve:{promotion_id}:{version}",
                    },
                    edit_and_cancel[0],
                ],
                [
                    add_photo,
                    edit_and_cancel[1],
                ],
            ]
        }

    def _send_review(self, promotion: dict[str, Any], now: datetime) -> None:
        if self.admin_id is None:
            self.store.mark_preview_failed(
                int(promotion["id"]),
                admin_id=0,
                at=_utc(now).isoformat(),
            )
            return
        deadline = _parse_time(str(promotion["review_deadline_at"]))
        scheduled_for = (
            _parse_time(str(promotion["scheduled_for"]))
            if promotion.get("scheduled_for")
            else None
        )
        if scheduled_for:
            review_line = (
                "It will publish automatically at "
                f"{scheduled_for.astimezone(WAT).strftime('%H:%M WAT')} if the final "
                "content and destination checks pass. No approval is needed. "
                "Add a photo if you want one; otherwise it will be text-only. "
                "Edit or cancel before publication."
            )
            scheduled_line = (
                f"Scheduled: {scheduled_for.astimezone(WAT).strftime('%A, %d %b %Y at %I:%M %p WAT')}\n"
            )
        else:
            review_line = (
                "Approve within five minutes (until "
                f"{deadline.astimezone(WAT).strftime('%H:%M WAT') if deadline else 'deadline unavailable'})."
            )
            scheduled_line = ""
        caption = (
            "🔒 <b>PRIVATE REVIEW — NOT PUBLISHED</b>\n"
            f"Target: {html.escape(str(promotion['group_title']))} · "
            f"Market Analysis topic (thread {promotion['thread_id']})\n"
            f"Market Analysis channel: {html.escape(str(promotion['channel_title']))}\n"
            f"{scheduled_line}{review_line}\n\n"
            f"{self._render(str(promotion['body']))}"
        )
        keyboard = self._review_keyboard(promotion)
        try:
            if promotion.get("photo_file_id"):
                result = self.api.send_photo_with_result(
                    self.admin_id,
                    str(promotion["photo_file_id"]),
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            else:
                result = self.api.send_message_with_result(
                    self.admin_id,
                    caption,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
        except TelegramAPIError:
            self.store.mark_preview_failed(
                int(promotion["id"]),
                admin_id=self.admin_id,
                version=int(promotion["review_version"]),
                at=_utc(now).isoformat(),
            )
            self.api.send_message(
                self.admin_id,
                "The private review could not be delivered. The group was not contacted.",
            )
            return
        if not isinstance(result.get("message_id"), int):
            self.store.mark_preview_failed(
                int(promotion["id"]),
                admin_id=self.admin_id,
                version=int(promotion["review_version"]),
                at=_utc(now).isoformat(),
            )
            self.api.send_message(
                self.admin_id,
                "The private review was not confirmed by Telegram. The group was not contacted.",
            )
            return
        self.store.mark_preview_sent(
            int(promotion["id"]),
            admin_id=self.admin_id,
            version=int(promotion["review_version"]),
            at=_utc(now).isoformat(),
        )

    def show_controls(self, chat_id: int) -> None:
        settings = self.store.settings()
        recent = self.store.recent(5)
        lines = [
            "<b>EDUCATION GROUP PROMOTIONS</b>",
            "Destination: Market Analysis topic in the Education forum group.",
            (
                f"Topic thread: {self.thread_id} (from the configured Telegram topic link)."
                if self.thread_id is not None and self.topic_config_error is None
                else "Topic thread: not configured; publishing is blocked."
            ),
            "Every post requires an explicit approval within five minutes.",
            "No approval means the draft expires without posting.",
            f"Manual promotion interval: once every {settings['cooldown_days']} days.",
            (
                "Scheduled class promotions: Monday and Thursday at 7:00 PM WAT; "
                "private preview five minutes earlier; each post needs approval."
                if settings.get("scheduled_enabled")
                else "Scheduled Monday/Thursday class promotions: paused."
            ),
            "",
            "Recent promotions:",
        ]
        if recent:
            lines.extend(
                f"• #{row['id']} — {row['status']}"
                for row in recent
            )
        else:
            lines.append("• No promotion drafts yet.")
        keyboard = [
            [
                {
                    "text": "📝 Prepare Promotion Draft",
                    "callback_data": "admin:education_topic_promo:create",
                }
            ],
            [
                {
                    "text": f"Every week{' ✓' if settings['cooldown_days'] == 7 else ''}",
                    "callback_data": "admin:education_topic_promo:interval:7",
                },
                {
                    "text": f"Every 2 weeks{' ✓' if settings['cooldown_days'] == 14 else ''}",
                    "callback_data": "admin:education_topic_promo:interval:14",
                },
                {
                    "text": f"Every 4 weeks{' ✓' if settings['cooldown_days'] == 28 else ''}",
                    "callback_data": "admin:education_topic_promo:interval:28",
                },
            ],
            [
                {
                    "text": "⏸ Pause Mon/Thu schedule"
                    if settings.get("scheduled_enabled")
                    else "▶️ Enable Mon/Thu schedule",
                    "callback_data": (
                        "admin:education_topic_promo:schedule:disable"
                        if settings.get("scheduled_enabled")
                        else "admin:education_topic_promo:schedule:enable"
                    ),
                }
            ],
            [{"text": "🔙 Back to Admin Dashboard", "callback_data": "admin:home"}],
        ]
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            {"inline_keyboard": keyboard},
            parse_mode="HTML",
        )

    def handle_callback(
        self,
        chat_id: int,
        admin_id: int,
        is_private: bool,
        data: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        if not data.startswith("admin:education_topic_promo"):
            return False
        if not self._authorized(chat_id, admin_id, is_private):
            return True
        current = _utc(now or datetime.now(timezone.utc))
        parts = data.split(":")
        if data == "admin:education_topic_promo":
            self.show_controls(chat_id)
            return True
        if len(parts) == 4 and parts[2] == "interval":
            days = int(parts[3]) if parts[3].isdigit() else 0
            if self.store.set_cooldown(days, admin_id=admin_id, at=current.isoformat()):
                self.api.send_message(
                    chat_id, f"Group-promotion interval set to every {days} days."
                )
            else:
                self.api.send_message(chat_id, "That promotion interval is not supported.")
            self.show_controls(chat_id)
            return True
        if len(parts) == 4 and parts[2] == "schedule":
            if parts[3] in {"enable", "disable"}:
                enabled = parts[3] == "enable"
                self.store.set_schedule_enabled(
                    enabled, admin_id=admin_id, at=current.isoformat()
                )
                self.api.send_message(
                    chat_id,
                    "Monday/Thursday promotional previews are "
                    + ("enabled." if enabled else "paused."),
                )
            self.show_controls(chat_id)
            return True
        if data == "admin:education_topic_promo:create":
            self._create_preview(chat_id, admin_id, current)
            return True
        if len(parts) != 5 or not parts[3].isdigit() or not parts[4].isdigit():
            return True
        action, promotion_id, version = parts[2], int(parts[3]), int(parts[4])
        promotion = self.store.get(promotion_id)
        if not promotion or int(promotion["review_version"]) != version:
            self.api.send_message(chat_id, "That group promotion draft is unavailable.")
            return True
        if action == "approve":
            self._approve(chat_id, admin_id, promotion, version, current)
        elif action == "edit":
            if self.store.begin_edit(
                promotion_id,
                admin_id=admin_id,
                version=version,
                at=current.isoformat(),
            ):
                self.api.send_message(
                    chat_id,
                    f"Send the replacement caption in one message (up to {MAX_PROMO_BODY_CHARS} "
                    "characters). The verified channel and bot buttons and safety footer "
                    + (
                        "will stay attached. Approve the revised preview before the scheduled "
                        "publication time; the deadline will not be extended. "
                        if promotion.get("scheduled_for")
                        else "will stay attached. The revised preview gets a new five-minute review. "
                    )
                    + "Send /cancel to cancel this draft.",
                )
            else:
                self.api.send_message(chat_id, "This review is closed; no edit was saved.")
        elif action == "photo":
            if self.store.request_photo(
                promotion_id,
                admin_id=admin_id,
                version=version,
                at=current.isoformat(),
            ):
                self.api.send_message(
                    chat_id,
                    "Adding a picture is optional. Send one chart image before the "
                    "scheduled time if you want it included; if you do not, the approved "
                    "caption will still publish on schedule without a photo. "
                    + (
                        "An uploaded image creates a new preview that must be approved "
                        "before the scheduled time; the deadline will not be extended."
                        if promotion.get("scheduled_for")
                        else "An uploaded image creates a new preview and a fresh five-minute review."
                    ),
                )
            else:
                self.api.send_message(
                    chat_id,
                    "This post is already approved or its review window is closed. "
                    "No photo was requested.",
                )
        elif action == "cancel":
            changed = self.store.cancel(
                promotion_id,
                admin_id=admin_id,
                version=version,
                at=current.isoformat(),
            )
            self.api.send_message(
                chat_id,
                "Promotion cancelled. Nothing was posted."
                if changed
                else "This review is already closed.",
            )
        else:
            self.api.send_message(chat_id, "That promotion action is not available.")
        return True

    def _create_preview(
        self, chat_id: int, admin_id: int, now: datetime
    ) -> None:
        try:
            channel_link, _bot_link, username, group_title, channel_title = (
                self._verify_targets()
            )
        except ValueError as error:
            self.api.send_message(chat_id, str(error))
            return
        if self.store.has_active_promotion():
            self.api.send_message(
                chat_id,
                "An earlier promotion is still pending review or needs delivery "
                "verification. Resolve it before generating another draft.",
            )
            return
        body, generation_error = self._generate_body(
            now=now,
            promotion_type="manual",
        )
        if generation_error or body is None:
            self.api.send_message(chat_id, f"Promotion held: {generation_error}")
            return
        promotion, error = self.store.create_draft(
            body=body,
            group_chat_id=int(self.education_group_id),
            group_title=group_title,
            thread_id=int(self.thread_id),
            topic_source_link=self.topic_message_link,
            channel_link=channel_link,
            channel_title=channel_title,
            bot_username=username,
            admin_id=admin_id,
            now=now,
            generation_model=str(
                getattr(self.writer, "model", "gemini-3.5-flash-lite")
            ),
        )
        if error or promotion is None:
            self.api.send_message(chat_id, error or "The draft could not be saved.")
            return
        self._send_review(promotion, now)

    @staticmethod
    def _scheduled_slot(now: datetime) -> tuple[str, datetime, datetime] | None:
        local_now = _utc(now).astimezone(WAT)
        weekday = {0: "monday", 3: "thursday"}.get(local_now.weekday())
        if weekday is None:
            return None
        local_scheduled = local_now.replace(
            hour=PROMO_SCHEDULE_TIME.hour,
            minute=PROMO_SCHEDULE_TIME.minute,
            second=0,
            microsecond=0,
        )
        scheduled_utc = local_scheduled.astimezone(timezone.utc)
        schedule_key = f"education-topic-promo:{local_now.date().isoformat()}:{weekday}"
        return schedule_key, scheduled_utc, local_scheduled

    def _notify_schedule_issue(self, message: str) -> None:
        if self.admin_id is None:
            logger.error("Education-topic scheduled promotion issue: %s", message)
            return
        try:
            self.api.send_message(self.admin_id, message)
        except TelegramAPIError:
            logger.exception("Could not notify the admin about a scheduled promotion issue.")

    def _create_scheduled_preview(
        self,
        *,
        now: datetime,
        schedule_key: str,
        scheduled_for: datetime,
        local_scheduled: datetime,
        weekday: str,
    ) -> None:
        if self.store.schedule_run(schedule_key):
            return
        if self.store.has_active_promotion():
            logger.info(
                "Scheduled promotion waiting for active review schedule_key=%s",
                schedule_key,
            )
            return
        if self.admin_id is None:
            details = "admin private-chat destination is not configured"
            if self.store.record_schedule_event(
                schedule_key=schedule_key,
                scheduled_for=scheduled_for,
                status="failed",
                details=details,
                at=_utc(now).isoformat(),
            ):
                self._notify_schedule_issue(
                    "The Monday/Thursday promotion was held: admin private chat is not configured."
                )
            return
        try:
            channel_link, _bot_link, username, group_title, channel_title = (
                self._verify_targets()
            )
        except ValueError as error:
            if self.store.record_schedule_event(
                schedule_key=schedule_key,
                scheduled_for=scheduled_for,
                status="failed",
                details=f"destination verification failed: {error}",
                at=_utc(now).isoformat(),
                admin_id=self.admin_id,
            ):
                self._notify_schedule_issue(
                    f"Scheduled promotion held; destination verification failed: {error}"
                )
            return
        body, generation_error = self._generate_body(
            now=now,
            promotion_type="scheduled_class",
            weekday=weekday.title(),
        )
        if generation_error or body is None:
            if self.store.record_schedule_event(
                schedule_key=schedule_key,
                scheduled_for=scheduled_for,
                status="failed",
                details=f"Gemini generation failed: {generation_error}",
                at=_utc(now).isoformat(),
                admin_id=self.admin_id,
            ):
                self._notify_schedule_issue(
                    f"Scheduled promotion held: {generation_error}"
                )
            return
        promotion, error = self.store.create_draft(
            body=body,
            group_chat_id=int(self.education_group_id),
            group_title=group_title,
            thread_id=int(self.thread_id),
            topic_source_link=self.topic_message_link,
            channel_link=channel_link,
            channel_title=channel_title,
            bot_username=username,
            admin_id=self.admin_id,
            now=now,
            scheduled_for=scheduled_for,
            schedule_key=schedule_key,
            generation_model=str(
                getattr(self.writer, "model", "gemini-3.5-flash-lite")
            ),
        )
        if error or promotion is None:
            # A manual draft can temporarily occupy the one-at-a-time slot.
            # Keep trying during the five-minute review window, then record a
            # missed schedule once the publication time passes.
            if error and "earlier group promotion" in error:
                logger.info(
                    "Scheduled promotion waiting for active review schedule_key=%s",
                    schedule_key,
                )
                return
            if self.store.record_schedule_event(
                schedule_key=schedule_key,
                scheduled_for=scheduled_for,
                status="failed",
                details=error or "draft creation failed",
                at=_utc(now).isoformat(),
                admin_id=self.admin_id,
            ):
                self._notify_schedule_issue(
                    f"Scheduled promotion was not prepared: {error or 'draft creation failed'}"
                )
            return
        self._send_review(promotion, now)
        logger.info(
            "Education topic scheduled preview created promotion_id=%s "
            "schedule_key=%s target_chat_id=%s thread_id=%s scheduled_for_wat=%s",
            promotion["id"],
            schedule_key,
            self.education_group_id,
            self.thread_id,
            local_scheduled.isoformat(),
        )

    def _publish_scheduled_post(
        self, promotion: dict[str, Any], now: datetime
    ) -> None:
        promotion_id = int(promotion["id"])
        if self.admin_id is None:
            self.store.fail_scheduled_review(
                promotion_id,
                admin_id=None,
                category="admin_private_chat_unavailable",
                at=_utc(now).isoformat(),
            )
            return
        issue = self._validate_body(
            str(promotion["body"]),
            promotion_type=(
                "scheduled_class" if promotion.get("schedule_key") else "manual"
            ),
        )
        if issue:
            self.store.fail_scheduled_review(
                promotion_id,
                admin_id=self.admin_id,
                category=f"content_validation:{issue}",
                at=_utc(now).isoformat(),
            )
            self._notify_schedule_issue(
                f"Scheduled promotion #{promotion_id} was held: {issue}"
            )
            return
        try:
            channel_link, bot_link, username, _group_title, _channel_title = (
                self._verify_targets()
            )
        except ValueError as error:
            self.store.fail_scheduled_review(
                promotion_id,
                admin_id=self.admin_id,
                category="destination_verification_failed",
                at=_utc(now).isoformat(),
            )
            self._notify_schedule_issue(
                f"Scheduled promotion #{promotion_id} was held because destination "
                f"verification failed: {error}"
            )
            return
        if (
            channel_link != promotion["channel_link"]
            or username != promotion["bot_username"]
            or promotion["group_chat_id"] != self.education_group_id
            or promotion["thread_id"] != self.thread_id
        ):
            self.store.fail_scheduled_review(
                promotion_id,
                admin_id=self.admin_id,
                category="destination_changed_after_preview",
                at=_utc(now).isoformat(),
            )
            self._notify_schedule_issue(
                f"Scheduled promotion #{promotion_id} was held because its verified "
                "destination changed after preview."
            )
            return
        if not self.store.claim_scheduled_publish(
            promotion_id,
            admin_id=self.admin_id,
            version=int(promotion["review_version"]),
            at=_utc(now).isoformat(),
        ):
            return
        self._publish_claimed(
            chat_id=self.admin_id,
            admin_id=self.admin_id,
            promotion=promotion,
            channel_link=channel_link,
            bot_link=bot_link,
            now=now,
        )

    def _approve(
        self,
        chat_id: int,
        admin_id: int,
        promotion: dict[str, Any],
        version: int,
        now: datetime,
    ) -> None:
        promotion_id = int(promotion["id"])
        issue = self._validate_body(
            str(promotion["body"]),
            promotion_type=(
                "scheduled_class" if promotion.get("schedule_key") else "manual"
            ),
        )
        if issue:
            self.api.send_message(chat_id, f"Not published: {issue}")
            return
        try:
            channel_link, bot_link, username, _group_title, _channel_title = (
                self._verify_targets()
            )
        except ValueError as error:
            self.api.send_message(chat_id, f"Not published: {error}")
            return
        if (
            channel_link != promotion["channel_link"]
            or username != promotion["bot_username"]
            or promotion["group_chat_id"] != self.education_group_id
            or promotion["thread_id"] != self.thread_id
        ):
            self.api.send_message(
                chat_id,
                "Not published: the verified link or destination changed after preview. "
                "Cancel this draft and prepare a fresh one.",
            )
            return
        if promotion.get("scheduled_for"):
            if not self.store.approve_scheduled(
                promotion_id,
                admin_id=admin_id,
                version=version,
                at=_utc(now).isoformat(),
            ):
                self.api.send_message(
                    chat_id,
                    "Not scheduled: approval was late, the preview was not delivered, "
                    "or this post was already handled.",
                )
                return
            scheduled_for = _parse_time(str(promotion["scheduled_for"]))
            scheduled_label = (
                scheduled_for.astimezone(WAT).strftime("%A at %I:%M %p WAT")
                if scheduled_for
                else "the scheduled time"
            )
            self.api.send_message(
                chat_id,
                f"Approved. The post is queued for {scheduled_label}; it will publish "
                "only if the final destination and content checks pass.",
            )
            return
        if not self.store.claim_publish(
            promotion_id,
            admin_id=admin_id,
            version=version,
            at=_utc(now).isoformat(),
        ):
            self.api.send_message(
                chat_id,
                "Not published: approval was late, the preview was not delivered, or "
                "this draft has already been handled.",
            )
            return
        self._publish_claimed(
            chat_id=chat_id,
            admin_id=admin_id,
            promotion=promotion,
            channel_link=channel_link,
            bot_link=bot_link,
            now=now,
        )

    def _publish_claimed(
        self,
        *,
        chat_id: int,
        admin_id: int,
        promotion: dict[str, Any],
        channel_link: str,
        bot_link: str,
        now: datetime | None = None,
    ) -> None:
        promotion_id = int(promotion["id"])
        sent_at = _utc(now or datetime.now(timezone.utc)).isoformat()
        text = self._render(str(promotion["body"]))
        keyboard = self._member_keyboard(channel_link, bot_link)
        try:
            if promotion.get("photo_file_id"):
                result = self.api.send_photo_with_result(
                    int(self.education_group_id),
                    str(promotion["photo_file_id"]),
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    message_thread_id=int(self.thread_id),
                )
            else:
                result = self.api.send_message_with_result(
                    int(self.education_group_id),
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    message_thread_id=int(self.thread_id),
                )
        except TelegramAPIError as error:
            unknown = error.delivery_unknown or (
                error.http_status is not None and error.http_status >= 500
            )
            self.store.fail_publish(
                promotion_id,
                admin_id=admin_id,
                category="telegram_delivery_unknown" if unknown else "telegram_rejected",
                delivery_unknown=unknown,
                at=sent_at,
            )
            message = (
                "Telegram’s response did not confirm whether the post was delivered. "
                "I will not retry automatically; check the Market Analysis topic first."
                if unknown
                else f"Telegram rejected the post: {str(error)[:240]}. No automatic retry was made."
            )
            self.api.send_message(chat_id, message)
            return
        message_id = result.get("message_id")
        if not isinstance(message_id, int) or isinstance(message_id, bool):
            self.store.fail_publish(
                promotion_id,
                admin_id=admin_id,
                category="telegram_message_id_missing",
                delivery_unknown=True,
                at=sent_at,
            )
            self.api.send_message(
                chat_id,
                "Telegram accepted the request but returned no message ID. Delivery "
                "is uncertain; check the topic before taking any further action.",
            )
            return
        self.store.finish_publish(
            promotion_id, message_id, admin_id=admin_id, at=sent_at
        )
        logger.info(
            "Education topic promotion published promotion_id=%s target_chat_id=%s "
            "thread_id=%s message_id=%s",
            promotion_id,
            self.education_group_id,
            self.thread_id,
            message_id,
        )
        self.api.send_message(
            chat_id,
            f"Published in the Market Analysis topic. Telegram message ID: {message_id}.",
        )

    def handle_admin_text(
        self,
        chat_id: int,
        admin_id: int,
        text: str,
        *,
        is_private: bool,
        now: datetime | None = None,
    ) -> bool:
        if not self._authorized(chat_id, admin_id, is_private):
            return False
        current = _utc(now or datetime.now(timezone.utc))
        if not self.has_input_pending(admin_id, now=current):
            return False
        if text.strip().casefold() == "/cancel":
            promotion_id = self.store.cancellable_input_for_admin(
                admin_id, at=current.isoformat()
            )
            if promotion_id is not None:
                self.store.cancel(
                    promotion_id,
                    admin_id=admin_id,
                    version=None,
                    at=current.isoformat(),
                )
            self.api.send_message(chat_id, "Promotion cancelled. Nothing was posted.")
            return True
        promotion = self.store.editing_for_admin(
            admin_id, at=current.isoformat()
        )
        if promotion is None:
            self.api.send_message(
                chat_id, "A photo is pending. Send one image or use /cancel."
            )
            return True
        body = " ".join(text.strip().split())
        issue = self._validate_body(
            body,
            promotion_type=(
                "scheduled_class" if promotion.get("schedule_key") else "manual"
            ),
        )
        if issue:
            self.api.send_message(chat_id, f"Caption not saved: {issue} Try again or /cancel.")
            return True
        if not self.store.save_edit(
            int(promotion["id"]),
            body,
            admin_id=admin_id,
            now=current,
        ):
            self.api.send_message(chat_id, "The edit window has closed; nothing was changed.")
            return True
        refreshed = self.store.get(int(promotion["id"]))
        if refreshed:
            self._send_review(refreshed, current)
        return True

    def handle_admin_photo(
        self,
        chat_id: int,
        admin_id: int,
        photos: Any,
        *,
        is_private: bool,
        now: datetime | None = None,
    ) -> bool:
        if not self._authorized(chat_id, admin_id, is_private):
            return False
        current = _utc(now or datetime.now(timezone.utc))
        pending = self.store.pending_photo(admin_id, at=current.isoformat())
        if pending is None:
            return False
        if not isinstance(photos, list):
            self.api.send_message(chat_id, "Telegram did not provide a usable image.")
            return True
        photo = max(
            (
                item
                for item in photos
                if isinstance(item, dict)
                and isinstance(item.get("file_id"), str)
                and 0 < len(item["file_id"].strip()) <= 2048
            ),
            key=lambda item: item.get("file_size", 0)
            if isinstance(item.get("file_size"), int)
            else 0,
            default=None,
        )
        if photo is None:
            self.api.send_message(chat_id, "No usable Telegram image was found; try again or /cancel.")
            return True
        promotion_id = int(pending["id"])
        if not self.store.attach_photo(
            promotion_id,
            str(photo["file_id"]),
            admin_id=admin_id,
            now=current,
        ):
            self.api.send_message(chat_id, "The photo window has closed; no image was attached.")
            return True
        refreshed = self.store.get(promotion_id)
        if refreshed:
            self._send_review(refreshed, current)
        return True

    def _dispatch_scheduled_promotions(self, now: datetime) -> None:
        settings = self.store.settings()
        if not settings.get("scheduled_enabled"):
            return
        slot = self._scheduled_slot(now)
        if slot is None:
            return
        schedule_key, scheduled_for, local_scheduled = slot
        local_now = _utc(now).astimezone(WAT)
        preview_at = local_scheduled - PROMO_REVIEW_LEAD
        if preview_at <= local_now < local_scheduled:
            if local_now <= preview_at + PROMO_REVIEW_LATE_TOLERANCE:
                weekday = "monday" if local_scheduled.weekday() == 0 else "thursday"
                self._create_scheduled_preview(
                    now=now,
                    schedule_key=schedule_key,
                    scheduled_for=scheduled_for,
                    local_scheduled=local_scheduled,
                    weekday=weekday,
                )
            return
        if local_now < local_scheduled:
            return
        if not self.store.schedule_run(schedule_key):
            details = "review window missed; no scheduled promotion was published"
            if self.store.record_schedule_event(
                schedule_key=schedule_key,
                scheduled_for=scheduled_for,
                status="missed",
                details=details,
                at=_utc(now).isoformat(),
            ):
                self._notify_schedule_issue(
                    "The Monday/Thursday promotion missed its private review window. "
                    "Nothing was posted."
                )
            return
        for promotion in self.store.scheduled_posts_due(at=_utc(now).isoformat()):
            if promotion.get("schedule_key") == schedule_key:
                self._publish_scheduled_post(promotion, now)

    def dispatch_due(self, now: datetime | None = None) -> None:
        current = _utc(now or datetime.now(timezone.utc))
        if not self._recovery_checked:
            self._recovery_checked = True
            recovered = self.store.recover_interrupted(at=current.isoformat())
            if self.admin_id is not None:
                for item in recovered:
                    note = (
                        "Delivery may have happened before restart. Check the Market "
                        "Analysis topic; the bot will not retry this promotion."
                        if item["status"] == "delivery_unknown"
                        else "The private preview was not confirmed before restart. "
                        "No group post was sent."
                    )
                    try:
                        self.api.send_message(
                            self.admin_id,
                            f"Promotion #{item['id']} needs attention: {note}",
                        )
                    except TelegramAPIError:
                        logger.warning(
                            "Could not notify admin about recovered group promo %s.",
                            item["id"],
                        )
        try:
            self._dispatch_scheduled_promotions(current)
        except Exception:
            logger.exception("Could not dispatch scheduled Monday/Thursday promotions.")
        expired = self.store.expire_due(at=current.isoformat())
        for promotion in expired:
            was_approved = promotion.get("approved_at") is not None
            logger.info(
                "Education topic promo expired without publication id=%s target_chat_id=%s "
                "thread_id=%s approved=%s",
                promotion["id"],
                promotion["group_chat_id"],
                promotion["thread_id"],
                was_approved,
            )
            if self.admin_id is not None:
                try:
                    self.api.send_message(
                        self.admin_id,
                        (
                            f"Scheduled promotion #{promotion['id']} missed its publication "
                            "window. It was not posted late."
                            if promotion.get("scheduled_for")
                            else (
                                f"Promotion draft #{promotion['id']} was approved but missed "
                                "its scheduled publication window. It was not posted late."
                                if was_approved
                                else f"Promotion draft #{promotion['id']} expired without approval. "
                                "Nothing was posted."
                            )
                        ),
                    )
                except TelegramAPIError:
                    logger.warning(
                        "Could not notify admin that group promotion %s expired.",
                        promotion["id"],
                    )

