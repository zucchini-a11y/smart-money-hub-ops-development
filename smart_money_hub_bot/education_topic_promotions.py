"""Admin-approved, one-at-a-time promotions for the Education Market Analysis topic."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from .education_polls import (
    EXPECTED_EDUCATION_GROUP_ID,
    EXPECTED_MARKET_ANALYSIS_CHANNEL_ID,
    parse_education_poll_message_link,
)
from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)

REVIEW_WINDOW = timedelta(minutes=5)
DEFAULT_COOLDOWN_DAYS = 14
ALLOWED_COOLDOWNS = {7, 14, 28}
MAX_PROMO_BODY_CHARS = 700
EXPECTED_BOT_USERNAME = "SmartMoneyHubSignalsBot"

_PROMO_BODIES = (
    "Looking for a separate place to follow Smart Money Hub market analysis? "
    "Visit the Market Analysis channel for its trading-focused posts, and use "
    "the bot to explore Smart Money Hub’s learning tools.",
    "Keep your learning and market updates easy to find. The Market Analysis "
    "channel and Smart Money Hub bot are available below for separate purposes: "
    "market-focused posts in the channel, learning tools in the bot.",
    "Want to follow the Market Analysis channel or explore the Smart Money Hub "
    "bot? Use the buttons below to open the right place. Keep your plan first "
    "and treat analysis as context, not an entry signal.",
)

_DISALLOWED_PROMO_CLAIMS = re.compile(
    r"\b(?:guaranteed\s+(?:profit|profits|returns)|"
    r"risk[\s-]?free\s+(?:profit|trading|returns)|"
    r"100%\s+(?:win(?:ning)?|profit)|"
    r"buy\s+now|sell\s+now|"
    r"we\s+(?:made|earned|won)\s+\$?\d)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


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
                    last_published_at TEXT,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO education_topic_promo_settings (id, updated_at)
                VALUES (1, CURRENT_TIMESTAMP);

                CREATE TABLE IF NOT EXISTS education_topic_promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    body TEXT NOT NULL,
                    body_hash TEXT NOT NULL,
                    group_chat_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    topic_source_link TEXT NOT NULL,
                    channel_link TEXT NOT NULL,
                    bot_username TEXT NOT NULL,
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
        promotion_id: int,
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
                "last_published_at": None,
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

    def create_draft(
        self,
        *,
        body: str,
        group_chat_id: int,
        thread_id: int,
        topic_source_link: str,
        channel_link: str,
        bot_username: str,
        admin_id: int,
        now: datetime,
    ) -> tuple[dict[str, Any] | None, str | None]:
        current = _utc(now)
        timestamp = current.isoformat()
        deadline = (current + REVIEW_WINDOW).isoformat()
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
            if last_published and current < last_published + timedelta(days=cooldown_days):
                available_at = (last_published + timedelta(days=cooldown_days)).isoformat()
                connection.rollback()
                return None, f"Posting frequency limit reached; another promotion is available after {available_at}."
            duplicate = connection.execute(
                """
                SELECT id FROM education_topic_promotions
                WHERE status = 'published' AND body_hash = ?
                LIMIT 1
                """,
                (digest,),
            ).fetchone()
            if duplicate:
                connection.rollback()
                return None, "This promotion wording has already been published. A fresh draft is required."
            cursor = connection.execute(
                """
                INSERT INTO education_topic_promotions (
                    body, body_hash, group_chat_id, thread_id, topic_source_link,
                    channel_link, bot_username, status, review_started_at,
                    review_deadline_at, review_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'review', ?, ?, 1, ?, ?)
                """,
                (
                    body,
                    digest,
                    group_chat_id,
                    thread_id,
                    topic_source_link,
                    channel_link,
                    bot_username,
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
                f"target_chat_id={group_chat_id};thread_id={thread_id}",
                timestamp,
            )
            connection.execute(
                """
                UPDATE education_topic_promo_settings
                SET next_variant_index = next_variant_index + 1, updated_at = ?
                WHERE id = 1
                """,
                (timestamp,),
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
                    "SELECT group_chat_id, thread_id FROM education_topic_promotions WHERE id = ?",
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
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET body = ?, body_hash = ?, status = 'review', edit_admin_id = NULL,
                    review_started_at = ?, review_deadline_at = ?, review_sent_at = NULL,
                    photo_upload_pending = 0, photo_upload_admin_id = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'editing' AND edit_admin_id = ?
                    AND review_deadline_at > ?
                """,
                (
                    body,
                    _body_hash(body),
                    timestamp,
                    (current + REVIEW_WINDOW).isoformat(),
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
                SET photo_upload_pending = 1, photo_upload_admin_id = ?, updated_at = ?
                WHERE id = ? AND status = 'review' AND review_sent_at IS NOT NULL
                    AND review_deadline_at > ? AND review_version = ?
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

    def attach_photo(
        self, promotion_id: int, file_id: str, *, admin_id: int, now: datetime
    ) -> bool:
        current = _utc(now)
        timestamp = current.isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE education_topic_promotions
                SET photo_file_id = ?, photo_upload_pending = 0,
                    photo_upload_admin_id = NULL, review_started_at = ?,
                    review_deadline_at = ?, review_sent_at = NULL,
                    review_version = review_version + 1, updated_at = ?
                WHERE id = ? AND photo_upload_pending = 1
                    AND photo_upload_admin_id = ? AND status = 'review'
                    AND review_deadline_at > ?
                """,
                (
                    file_id,
                    timestamp,
                    (current + REVIEW_WINDOW).isoformat(),
                    timestamp,
                    promotion_id,
                    admin_id,
                    timestamp,
                ),
            )
            if cursor.rowcount:
                self._action(connection, promotion_id, "photo_attached", admin_id, "", timestamp)
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
                    updated_at = ?
                WHERE id = ? AND status = 'review' AND review_sent_at IS NOT NULL
                    AND review_deadline_at > ? AND publish_attempts = 0
                    AND review_version = ?
                """,
                (at, promotion_id, at, version),
            )
            if cursor.rowcount:
                row = connection.execute(
                    "SELECT group_chat_id, thread_id FROM education_topic_promotions WHERE id = ?",
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
                    "SELECT group_chat_id, thread_id FROM education_topic_promotions WHERE id = ?",
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
                    "SELECT group_chat_id, thread_id FROM education_topic_promotions WHERE id = ?",
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

    def expire_due(self, *, at: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, group_chat_id, thread_id
                FROM education_topic_promotions
                WHERE status IN ('review', 'editing') AND review_deadline_at <= ?
                """,
                (at,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE education_topic_promotions
                    SET status = 'expired', photo_upload_pending = 0,
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
            return [dict(row) for row in rows]


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
    ) -> None:
        self.api = api
        self.admin_id = admin_id
        self.education_group_id = education_group_id
        self.market_channel_id = market_channel_id
        self.topic_message_link = (topic_message_link or "").strip()
        self.store = EducationTopicPromotionStore(database_path)
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
            self.thread_id = thread_id
        except (TypeError, ValueError):
            self.topic_config_error = (
                "The configured Market Analysis topic link is missing or invalid. "
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

    def _verify_targets(self) -> tuple[str, str, str]:
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
        return channel_link, f"https://t.me/{username}", username

    @staticmethod
    def _body_for(index: int) -> str:
        return _PROMO_BODIES[index % len(_PROMO_BODIES)]

    @staticmethod
    def _validate_body(body: str) -> str | None:
        text = " ".join(body.split())
        if not text or len(text) > MAX_PROMO_BODY_CHARS:
            return f"Caption must be 1–{MAX_PROMO_BODY_CHARS} characters."
        if _URL.search(text):
            return "Keep links in the verified buttons; remove URLs from the caption."
        if _DISALLOWED_PROMO_CLAIMS.search(text):
            return "The caption contains a trading result, guaranteed claim, or direct signal."
        return None

    @staticmethod
    def _render(body: str) -> str:
        return (
            "📊 <b>SMART MONEY HUB | MARKET ANALYSIS</b>\n\n"
            f"{html.escape(body, quote=False)}\n\n"
            "🛡️ <b>NO CONFIRMATION, NO ENTRY.</b>\n\n"
            "For educational purposes only. Trading involves risk."
        )

    @staticmethod
    def _member_keyboard(channel_link: str, bot_link: str) -> dict[str, Any]:
        version = int(promotion["review_version"])
        promotion_id = int(promotion["id"])
        return {
            "inline_keyboard": [
                [{"text": "📊 Open Market Analysis", "url": channel_link}],
                [{"text": "🤖 Open Smart Money Hub Bot", "url": bot_link}],
            ]
        }

    def _review_keyboard(self, promotion: dict[str, Any]) -> dict[str, Any]:
        links = self._member_keyboard(
            str(promotion["channel_link"]),
            f"https://t.me/{promotion['bot_username']}",
        )["inline_keyboard"]
        return {
            "inline_keyboard": [
                *links,
                [
                    {
                        "text": "✅ Approve & Publish",
                        "callback_data": f"admin:education_topic_promo:approve:{promotion_id}:{version}",
                    },
                    {
                        "text": "✏️ Edit Caption",
                        "callback_data": f"admin:education_topic_promo:edit:{promotion_id}:{version}",
                    },
                ],
                [
                    {
                        "text": "🖼 Add Picture",
                        "callback_data": f"admin:education_topic_promo:photo:{promotion_id}:{version}",
                    },
                    {
                        "text": "Cancel",
                        "callback_data": f"admin:education_topic_promo:cancel:{promotion_id}:{version}",
                    },
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
        caption = (
            "🔒 <b>PRIVATE REVIEW — NOT PUBLISHED</b>\n"
            f"Target: Education group · Market Analysis topic · thread {promotion['thread_id']}\n"
            f"Approve within five minutes (until {deadline.strftime('%H:%M:%S UTC') if deadline else 'deadline unavailable'}).\n\n"
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
            f"Minimum interval: once every {settings['cooldown_days']} days.",
            "Automatic posting: disabled.",
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
                    "will stay attached. The revised preview gets a new five-minute review. "
                    "Send /cancel to cancel this draft.",
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
                    "Send one chart image now. The updated photo-and-caption preview "
                    "will start a fresh five-minute review window.",
                )
            else:
                self.api.send_message(chat_id, "This review is closed; no photo was requested.")
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
            channel_link, _bot_link, username = self._verify_targets()
        except ValueError as error:
            self.api.send_message(chat_id, str(error))
            return
        settings = self.store.settings()
        body = self._body_for(int(settings["next_variant_index"]))
        issue = self._validate_body(body)
        if issue:
            self.api.send_message(chat_id, f"Draft held: {issue}")
            return
        promotion, error = self.store.create_draft(
            body=body,
            group_chat_id=int(self.education_group_id),
            thread_id=int(self.thread_id),
            topic_source_link=self.topic_message_link,
            channel_link=channel_link,
            bot_username=username,
            admin_id=admin_id,
            now=now,
        )
        if error or promotion is None:
            self.api.send_message(chat_id, error or "The draft could not be saved.")
            return
        self._send_review(promotion, now)

    def _approve(
        self,
        chat_id: int,
        admin_id: int,
        promotion: dict[str, Any],
        version: int,
        now: datetime,
    ) -> None:
        promotion_id = int(promotion["id"])
        issue = self._validate_body(str(promotion["body"]))
        if issue:
            self.api.send_message(chat_id, f"Not published: {issue}")
            return
        try:
            channel_link, bot_link, username = self._verify_targets()
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
            unknown = error.delivery_unknown
            self.store.fail_publish(
                promotion_id,
                admin_id=admin_id,
                category="telegram_delivery_unknown" if unknown else "telegram_rejected",
                delivery_unknown=unknown,
                at=_utc(datetime.now(timezone.utc)).isoformat(),
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
                at=_utc(datetime.now(timezone.utc)).isoformat(),
            )
            self.api.send_message(
                chat_id,
                "Telegram accepted the request but returned no message ID. Delivery "
                "is uncertain; check the topic before taking any further action.",
            )
            return
        at = _utc(datetime.now(timezone.utc)).isoformat()
        self.store.finish_publish(
            promotion_id, message_id, admin_id=admin_id, at=at
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
            with self.store._connect() as connection:
                row = connection.execute(
                    """
                    SELECT id FROM education_topic_promotions
                    WHERE status IN ('editing', 'review')
                        AND (edit_admin_id = ? OR photo_upload_admin_id = ?)
                    ORDER BY id DESC LIMIT 1
                    """,
                    (admin_id, admin_id),
                ).fetchone()
            if row:
                self.store.cancel(
                    int(row["id"]), admin_id=admin_id, at=current.isoformat()
                )
            self.api.send_message(chat_id, "Promotion cancelled. Nothing was posted.")
            return True
        promotion = None
        with self.store._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM education_topic_promotions
                WHERE status = 'editing' AND edit_admin_id = ?
                    AND review_deadline_at > ?
                ORDER BY id DESC LIMIT 1
                """,
                (admin_id, current.isoformat()),
            ).fetchone()
            if row:
                promotion = dict(row)
        if promotion is None:
            self.api.send_message(
                chat_id, "A photo is pending. Send one image or use /cancel."
            )
            return True
        body = " ".join(text.strip().split())
        issue = self._validate_body(body)
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

    def dispatch_due(self, now: datetime | None = None) -> None:
        current = _utc(now or datetime.now(timezone.utc))
        expired = self.store.expire_due(at=current.isoformat())
        for promotion in expired:
            logger.info(
                "Education topic promo expired without publication id=%s target_chat_id=%s "
                "thread_id=%s",
                promotion["id"],
                promotion["group_chat_id"],
                promotion["thread_id"],
            )
            if self.admin_id is not None:
                try:
                    self.api.send_message(
                        self.admin_id,
                        f"Promotion draft #{promotion['id']} expired without approval. "
                        "Nothing was posted.",
                    )
                except TelegramAPIError:
                    logger.warning(
                        "Could not notify admin that group promotion %s expired.",
                        promotion["id"],
                    )

