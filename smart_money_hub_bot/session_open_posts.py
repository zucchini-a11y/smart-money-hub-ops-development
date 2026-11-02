"""DST-aware, duplicate-safe Market Analysis posts for major FX session opens."""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from difflib import SequenceMatcher
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .channel_content import (
    normalize_weekend_brand_header,
    render_weekend_post_html,
    validate_channel_post,
    validate_weekend_post_format,
)
from .channel_gemini import GeminiChannelContentService, GeminiChannelGenerationError
from .channel_posting import DestinationVerificationError
from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)
WAT = ZoneInfo("Africa/Lagos")
GENERATION_LEAD = timedelta(minutes=15)
FINAL_REVIEW_LEAD = timedelta(minutes=5)
MAX_RATE_LIMIT_RETRIES = 1
PAGE_SIZE = 12


@dataclass(frozen=True)
class SessionDefinition:
    code: str
    label: str
    timezone_name: str
    open_time: wall_time
    close_time: wall_time


@dataclass(frozen=True)
class SessionOccurrence:
    definition: SessionDefinition
    local_date: date
    local_at: datetime
    wat_at: datetime
    utc_at: datetime

    @property
    def schedule_date(self) -> str:
        return self.local_date.isoformat()

    @property
    def schedule_key(self) -> str:
        return f"{self.schedule_date}:{self.definition.code}"


SESSION_DEFINITIONS = (
    # Conventional FX session-open markers, not exchange-guaranteed hours.
    SessionDefinition(
        "asia", "Asia (Tokyo)", "Asia/Tokyo", wall_time(9, 0), wall_time(18, 0)
    ),
    SessionDefinition(
        "london", "London", "Europe/London", wall_time(8, 0), wall_time(17, 0)
    ),
    SessionDefinition(
        "new_york", "New York", "America/New_York", wall_time(8, 0), wall_time(17, 0)
    ),
)

_STATUS_VALUES = (
    "generating",
    "draft",
    "review_sending",
    "review_pending",
    "approved",
    "editing",
    "cancelled",
    "publishing",
    "published",
    "retry_wait",
    "failed",
    "delivery_unknown",
    "missed",
)
_TERMINAL_STATUSES = ("published", "delivery_unknown", "cancelled")
_DUPLICATE_RETRYABLE_FAILURE_PREFIXES = (
    "content_rejected_duplicate_content",
    "content_rejected_repeated_session_layout",
)
_CANONICAL = re.compile(r"[^a-z0-9]+")
_SESSION_LAYOUT_HEADINGS = (
    "WHAT TO PREPARE",
    "CONDITIONS TO WATCH",
    "SESSION CHECKLIST",
)


def validate_session_open_post(content: str, post: dict[str, Any]) -> str | None:
    """Apply channel gates and session requirements, including late-recovery rules."""
    rejection = validate_channel_post(
        content,
        is_promo=False,
        verified_information=(),
    ) or validate_weekend_post_format(content)
    if rejection:
        return rejection
    if str(post.get("category") or "") != "new_week_preparation":
        return "session_category_mismatch"
    upper = content.upper()
    late_recovery = bool(post.get("late_recovery"))
    if "SESSION OPEN" not in upper and not (
        late_recovery and "SESSION CHECK-IN" in upper
    ):
        return "session_headline_missing"
    if late_recovery and re.search(
        r"\b\d{1,2}:\d{2}\b|\b(?:WAT|JST|UTC|GMT)\b|"
        r"Asia/Tokyo|Europe/London|America/New_York",
        content,
        flags=re.IGNORECASE,
    ):
        return "session_recovery_time_in_copy"
    session_code = str(post.get("session_code") or "")
    required_names = {
        "asia": ("ASIA", "TOKYO"),
        "london": ("LONDON",),
        "new_york": ("NEW YORK",),
    }.get(session_code, ())
    if required_names and not any(name in upper for name in required_names):
        return "session_name_missing"
    local_time = str(post.get("session_local_time") or "").strip()
    wat_time = str(post.get("schedule_time_wat") or "").strip()
    if not local_time or not wat_time:
        return "session_schedule_time_missing"
    if not any(heading in upper for heading in _SESSION_LAYOUT_HEADINGS):
        return "session_template_section_missing"
    if "RISK REMINDER" not in upper and "RISK CHECK" not in upper:
        return "session_risk_reminder_missing"
    if "NO CONFIRMATION, NO ENTRY." not in upper:
        return "session_golden_rule_missing"
    return None


def _session_close_utc(occurrence: SessionOccurrence) -> datetime:
    """Return the conventional local session end, converted with DST awareness."""
    zone = ZoneInfo(occurrence.definition.timezone_name)
    local_close = datetime.combine(
        occurrence.local_date, occurrence.definition.close_time, tzinfo=zone
    )
    return local_close.astimezone(timezone.utc)


def _session_layout_heading(content: str) -> str | None:
    upper = content.upper()
    for heading in _SESSION_LAYOUT_HEADINGS:
        if heading in upper:
            return heading
    return None


def session_occurrences(target_date: date) -> list[SessionOccurrence]:
    """Return the three conventional local opens for a weekday in WAT and UTC."""
    if target_date.weekday() >= 5:
        return []
    occurrences: list[SessionOccurrence] = []
    for definition in SESSION_DEFINITIONS:
        zone = ZoneInfo(definition.timezone_name)
        local_at = datetime.combine(target_date, definition.open_time, tzinfo=zone)
        occurrences.append(
            SessionOccurrence(
                definition=definition,
                local_date=target_date,
                local_at=local_at,
                wat_at=local_at.astimezone(WAT),
                utc_at=local_at.astimezone(timezone.utc),
            )
        )
    return sorted(occurrences, key=lambda item: item.utc_at)


class SessionOpenPostStore:
    """Persistent state for independently scheduled session posts."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.recovery_events = self._recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _database(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._database() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_open_channel_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    schedule_date TEXT NOT NULL,
                    session_code TEXT NOT NULL CHECK (
                        session_code IN ('asia', 'london', 'new_york')
                    ),
                    session_label TEXT NOT NULL,
                    session_timezone TEXT NOT NULL,
                    session_local_time TEXT NOT NULL,
                    schedule_time_wat TEXT NOT NULL,
                    schedule_at_utc TEXT NOT NULL,
                    destination_chat_id INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT 'new_week_preparation',
                    content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'generating', 'draft', 'review_sending',
                            'review_pending', 'approved', 'editing', 'cancelled',
                            'publishing', 'published', 'retry_wait', 'failed',
                            'delivery_unknown', 'missed'
                        )
                    ),
                    late_recovery INTEGER NOT NULL DEFAULT 0
                        CHECK (late_recovery IN (0, 1)),
                    failure_category TEXT,
                    review_sent_at TEXT,
                    review_deadline_at TEXT,
                    edit_admin_id INTEGER,
                    edit_previous_status TEXT,
                    photo_file_id TEXT,
                    photo_upload_pending INTEGER NOT NULL DEFAULT 0
                        CHECK (photo_upload_pending IN (0, 1)),
                    photo_upload_admin_id INTEGER,
                    publish_attempts INTEGER NOT NULL DEFAULT 0,
                    publishing_started_at TEXT,
                    retry_after_at TEXT,
                    telegram_message_id INTEGER,
                    published_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (schedule_date, session_code)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS session_open_posts_due
                ON session_open_channel_posts (status, schedule_at_utc)
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(session_open_channel_posts)"
                ).fetchall()
            }
            if "edit_previous_status" not in columns:
                connection.execute(
                    "ALTER TABLE session_open_channel_posts "
                    "ADD COLUMN edit_previous_status TEXT"
                )
            if "late_recovery" not in columns:
                connection.execute(
                    "ALTER TABLE session_open_channel_posts "
                    "ADD COLUMN late_recovery INTEGER NOT NULL DEFAULT 0"
                )

    def _recover_interrupted(self) -> list[dict[str, Any]]:
        now = _utc_now()
        recovered: list[dict[str, Any]] = []
        with self._database() as connection:
            rows = connection.execute(
                """
                SELECT id, schedule_date, session_label, status, late_recovery
                FROM session_open_channel_posts
                WHERE status IN ('generating', 'review_sending', 'publishing')
                """
            ).fetchall()
            for row in rows:
                if row["status"] == "publishing":
                    status = "delivery_unknown"
                    category = "telegram_delivery_unknown"
                elif row["status"] == "generating" and row["late_recovery"]:
                    # Gemini generation is side-effect-free; it is safe to retry
                    # this recovery after restart while the session remains active.
                    status = "missed"
                    category = "session_open_late_generation_interrupted"
                else:
                    status = "failed"
                    category = (
                        "generation_interrupted"
                        if row["status"] == "generating"
                        else "review_delivery_unknown"
                    )
                connection.execute(
                    """
                    UPDATE session_open_channel_posts
                    SET status = ?, failure_category = ?, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (status, category, now, row["id"], row["status"]),
                )
                recovered.append(
                    {
                        "id": int(row["id"]),
                        "schedule_date": str(row["schedule_date"]),
                        "session_label": str(row["session_label"]),
                        "status": status,
                        "failure_category": category,
                    }
                )
        return recovered

    def create_slot(
        self,
        occurrence: SessionOccurrence,
        destination_chat_id: int,
        *,
        at: str,
    ) -> tuple[dict[str, Any], bool]:
        with self._database() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO session_open_channel_posts (
                    schedule_date, session_code, session_label,
                    session_timezone, session_local_time, schedule_time_wat,
                    schedule_at_utc, destination_chat_id, status, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'generating', ?, ?)
                """,
                (
                    occurrence.schedule_date,
                    occurrence.definition.code,
                    occurrence.definition.label,
                    occurrence.definition.timezone_name,
                    occurrence.local_at.strftime("%H:%M"),
                    occurrence.wat_at.strftime("%H:%M"),
                    occurrence.utc_at.isoformat(),
                    destination_chat_id,
                    at,
                    at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM session_open_channel_posts
                WHERE schedule_date = ? AND session_code = ?
                """,
                (
                    occurrence.schedule_date,
                    occurrence.definition.code,
                ),
            ).fetchone()
            return dict(row), bool(cursor.rowcount)

    def get(self, post_id: int) -> dict[str, Any] | None:
        with self._database() as connection:
            row = connection.execute(
                "SELECT * FROM session_open_channel_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_by_key(self, occurrence: SessionOccurrence) -> dict[str, Any] | None:
        with self._database() as connection:
            row = connection.execute(
                """
                SELECT * FROM session_open_channel_posts
                WHERE schedule_date = ? AND session_code = ?
                """,
                (occurrence.schedule_date, occurrence.definition.code),
            ).fetchone()
            return dict(row) if row else None

    def update(
        self,
        post_id: int,
        *,
        expected: tuple[str, ...],
        status: str,
        at: str,
        **fields: Any,
    ) -> bool:
        if status not in _STATUS_VALUES:
            raise ValueError("Invalid session-post status.")
        allowed_fields = {
            "content",
            "category",
            "failure_category",
            "late_recovery",
            "review_sent_at",
            "review_deadline_at",
            "edit_admin_id",
            "edit_previous_status",
            "photo_file_id",
            "photo_upload_pending",
            "photo_upload_admin_id",
            "publish_attempts",
            "publishing_started_at",
            "retry_after_at",
            "telegram_message_id",
            "published_at",
        }
        if set(fields) - allowed_fields:
            raise ValueError("Unsupported session-post field.")
        assignments = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, at]
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.extend([post_id, *expected])
        placeholders = ", ".join("?" for _ in expected)
        terminal_placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)
        values.extend(_TERMINAL_STATUSES)
        with self._database() as connection:
            cursor = connection.execute(
                f"""
                UPDATE session_open_channel_posts
                SET {", ".join(assignments)}
                WHERE id = ? AND status IN ({placeholders})
                    AND status NOT IN ({terminal_placeholders})
                """,
                values,
            )
            return bool(cursor.rowcount)

    def reserve_publish(self, post_id: int, *, at: str) -> int | None:
        with self._database() as connection:
            cursor = connection.execute(
                """
                UPDATE session_open_channel_posts
                SET status = 'publishing', publishing_started_at = ?,
                    retry_after_at = NULL, failure_category = NULL,
                    publish_attempts = publish_attempts + 1, updated_at = ?
                WHERE id = ? AND status IN (
                    'approved', 'review_pending', 'retry_wait'
                )
                """,
                (at, at, post_id),
            )
            if not cursor.rowcount:
                return None
            row = connection.execute(
                "SELECT publish_attempts FROM session_open_channel_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            return int(row["publish_attempts"])

    def list_upcoming(
        self, *, start_utc: datetime, limit: int = PAGE_SIZE
    ) -> list[dict[str, Any]]:
        with self._database() as connection:
            rows = connection.execute(
                """
                SELECT * FROM session_open_channel_posts
                WHERE schedule_at_utc >= ?
                ORDER BY schedule_at_utc, id LIMIT ?
                """,
                (start_utc.isoformat(), limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_recent(
        self, *, limit: int = 30, exclude_id: int | None = None
    ) -> list[dict[str, Any]]:
        exclusion = " AND id != ?" if exclude_id is not None else ""
        params: tuple[Any, ...] = (
            (exclude_id, limit) if exclude_id is not None else (limit,)
        )
        with self._database() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM session_open_channel_posts
                WHERE content != ''{exclusion}
                ORDER BY schedule_at_utc DESC LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def list_retryable_gemini_failures(
        self, *, since_date: date, limit: int = 3
    ) -> list[dict[str, Any]]:
        with self._database() as connection:
            rows = connection.execute(
                """
                SELECT * FROM session_open_channel_posts
                WHERE status = 'failed'
                  AND substr(failure_category, 1, 7) = 'gemini_'
                  AND content = ''
                  AND schedule_date >= ?
                ORDER BY schedule_at_utc DESC, id DESC
                LIMIT ?
                """,
                (since_date.isoformat(), limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def pending_edit(self, admin_id: int) -> dict[str, Any] | None:
        with self._database() as connection:
            row = connection.execute(
                """
                SELECT * FROM session_open_channel_posts
                WHERE status = 'editing' AND edit_admin_id = ?
                ORDER BY schedule_at_utc LIMIT 1
                """,
                (admin_id,),
            ).fetchone()
            return dict(row) if row else None

    def pending_photo(self, admin_id: int) -> dict[str, Any] | None:
        with self._database() as connection:
            row = connection.execute(
                """
                SELECT * FROM session_open_channel_posts
                WHERE photo_upload_pending = 1 AND photo_upload_admin_id = ?
                  AND status IN ('draft', 'review_pending', 'approved', 'failed')
                ORDER BY schedule_at_utc LIMIT 1
                """,
                (admin_id,),
            ).fetchone()
            return dict(row) if row else None


class SessionOpenPostManager:
    """Generate, preview, and safely publish one post at each selected session open."""

    def __init__(
        self,
        api: TelegramAPI,
        database_path: str | Path,
        *,
        admin_id: int | None,
        destination_chat_id: int | None,
        writer: GeminiChannelContentService | None,
        history_store: Any,
        channel_post_manager: Any,
    ) -> None:
        self.api = api
        self.admin_id = admin_id
        self.destination_chat_id = destination_chat_id
        self.writer = writer
        self.history_store = history_store
        self.channel_post_manager = channel_post_manager
        self.store = SessionOpenPostStore(database_path)
        self._recovery_notified = False

    def dispatch_due(self, now: datetime | None = None) -> None:
        current = _as_utc(now or datetime.now(timezone.utc))
        if self.admin_id is None or self.destination_chat_id is None:
            return
        if not self._recovery_notified:
            self._notify_recovery()
            self._recovery_notified = True

        today_wat = current.astimezone(WAT).date()
        for occurrence in session_occurrences(today_wat):
            remaining = occurrence.utc_at - current
            post = self.store.get_by_key(occurrence)

            if post is None and timedelta(0) < remaining <= GENERATION_LEAD:
                settings = self.history_store.get_channel_posting_settings()
                if settings.get("paused"):
                    post, created = self.store.create_slot(
                        occurrence, int(self.destination_chat_id), at=current.isoformat()
                    )
                    if created:
                        self._hold(
                            post,
                            "channel_publishing_paused",
                            "The session post was skipped because Market Analysis "
                            "publishing is paused. Nothing was sent.",
                        )
                    continue
                post, created = self.store.create_slot(
                    occurrence, int(self.destination_chat_id), at=current.isoformat()
                )
                if created:
                    self._generate(post, occurrence, current)
                    post = self.store.get(int(post["id"])) or post

            if post is None and remaining <= timedelta(0):
                missed_post, created = self.store.create_slot(
                    occurrence, int(self.destination_chat_id), at=current.isoformat()
                )
                if created:
                    self.store.update(
                        int(missed_post["id"]),
                        expected=("generating",),
                        status="missed",
                        at=current.isoformat(),
                        failure_category="session_open_missed",
                    )
                    self._notify(
                        f"The {occurrence.definition.label} session post for "
                        f"{occurrence.schedule_date} was missed while the bot was "
                        "unavailable. A fresh, time-free check-in will be generated "
                        "and published only if the session is still active and all "
                        "content and destination checks pass."
                    )
                post = self.store.get(int(missed_post["id"])) or missed_post

            if not post:
                continue
            status = str(post["status"])
            if status == "missed":
                self._recover_missed(post, occurrence, current)
                continue
            late_recovery = bool(post.get("late_recovery"))
            if late_recovery and current >= _session_close_utc(occurrence):
                already_held = (
                    status == "failed"
                    and post.get("failure_category")
                    == "session_open_recovery_window_expired"
                )
                terminal = status in {"published", "delivery_unknown", "cancelled"}
                if not already_held and not terminal:
                    self._hold(
                        post,
                        "session_open_recovery_window_expired",
                        "The session has ended, so the late replacement was held instead "
                        "of publishing stale session content.",
                    )
                continue
            if status == "draft" and timedelta(0) < remaining <= FINAL_REVIEW_LEAD:
                self._send_review(post, occurrence, current)
                post = self.store.get(int(post["id"])) or post
                status = str(post["status"])
            if remaining <= timedelta(0):
                if (
                    status in {"approved", "review_pending", "retry_wait"}
                    and current - occurrence.utc_at > timedelta(minutes=5)
                    and not late_recovery
                ):
                    self._hold(
                        post,
                        "session_open_deadline_passed",
                        "The session opening was missed by more than five minutes. "
                        "The post was held instead of being sent late.",
                    )
                    continue
                if status == "editing":
                    self._hold(
                        post,
                        "session_review_edit_incomplete",
                        "The session post was not published because its edit was "
                        "still incomplete at the scheduled opening.",
                    )
                elif status == "draft":
                    self._hold(
                        post,
                        "session_review_missed",
                        "The session post was held because its private review was "
                        "not delivered before the opening.",
                    )
                elif status in {"approved", "review_pending"}:
                    self._publish(post, current)
                elif status == "retry_wait" and self._retry_due(post, current):
                    self._publish(post, current)

    def _recover_missed(
        self,
        post: dict[str, Any],
        occurrence: SessionOccurrence,
        current: datetime,
    ) -> None:
        """Generate and publish one fresh replacement while the session is active."""
        failure_category = str(post.get("failure_category") or "")
        retryable_miss = failure_category == "session_open_missed" or (
            bool(post.get("late_recovery"))
            and failure_category == "session_open_late_generation_interrupted"
        )
        if not retryable_miss or current < occurrence.utc_at:
            return
        if current >= _session_close_utc(occurrence):
            if failure_category != "session_open_recovery_window_expired":
                self.store.update(
                    int(post["id"]),
                    expected=("missed",),
                    status="missed",
                    at=current.isoformat(),
                    failure_category="session_open_recovery_window_expired",
                )
                self._notify(
                    f"The {occurrence.definition.label} session has ended. Its missed "
                    "post remains unpublished; no stale replacement was sent."
                )
            return
        if self.history_store.get_channel_posting_settings().get("paused"):
            self._hold(
                post,
                "channel_publishing_paused",
                "The session was missed while Market Analysis publishing is paused. "
                "The fresh replacement remains held; nothing was sent.",
            )
            return
        claimed = self.store.update(
            int(post["id"]),
            expected=("missed",),
            status="generating",
            at=current.isoformat(),
            failure_category="session_open_late_recovery",
            late_recovery=1,
        )
        if not claimed:
            return
        claimed_post = self.store.get(int(post["id"])) or post
        self._generate(claimed_post, occurrence, current, late_recovery=True)
        generated = self.store.get(int(post["id"]))
        if not generated or generated.get("status") != "draft":
            return
        if self.store.update(
            int(post["id"]),
            expected=("draft",),
            status="approved",
            at=current.isoformat(),
            failure_category="session_open_late_recovery",
            late_recovery=1,
        ):
            approved = self.store.get(int(post["id"])) or generated
            self._publish(approved, current)

    def show_controls(self, chat_id: int, *, now: datetime | None = None) -> None:
        current = _as_utc(now or datetime.now(timezone.utc))
        today = current.astimezone(WAT).date()
        occurrences: list[SessionOccurrence] = []
        for offset in range(0, 8):
            day = today + timedelta(days=offset)
            occurrences.extend(
                item
                for item in session_occurrences(day)
                if item.utc_at >= current
            )
            if len(occurrences) >= PAGE_SIZE:
                break
        records = {
            (str(item["schedule_date"]), str(item["session_code"])): item
            for item in self.store.list_upcoming(start_utc=current, limit=PAGE_SIZE)
        }
        lines = [
            "SESSION-OPEN MARKET ANALYSIS POSTS",
            "Extra weekday posts at each session open:",
            "Asia: Tokyo 09:00 JST; London: 08:00 Europe/London; "
            "New York: 08:00 America/New_York.",
            "Times convert to WAT with daylight-saving changes where applicable. "
            "These are conventional FX session markers, not exchange-guaranteed hours.",
            "Gemini prepares an evergreen post 15 minutes before; a private review "
            "arrives 5 minutes before. Approve, edit, cancel, or add a photo. If "
            "there is no response, eligible posts publish at the open.",
            "If an open was missed while the bot was unavailable, Gemini prepares "
            "a fresh check-in without public schedule times and it may auto-publish "
            "only while that session is still active and all checks pass. Once the "
            "session has ended, the missed post stays unpublished.",
            "No live prices or unverified news are invented. Publishing pause, "
            "destination checks, and content validators still apply.",
            "",
            "Upcoming session slots:",
        ]
        rows: list[list[dict[str, str]]] = []
        for occurrence in occurrences[:PAGE_SIZE]:
            key = (occurrence.schedule_date, occurrence.definition.code)
            post = records.get(key)
            if post:
                status = str(post["status"]).replace("_", " ").title()
                label = (
                    f"{occurrence.schedule_date} · {occurrence.definition.label} "
                    f"{occurrence.wat_at.strftime('%H:%M')} WAT — {status}"
                )
                if post.get("content"):
                    rows.append(
                        [
                            {
                                "text": (
                                    f"👁 {occurrence.definition.label} · "
                                    f"{occurrence.schedule_date}"
                                )[:64],
                                "callback_data": f"admin:session_open:preview:{post['id']}",
                            }
                        ]
                    )
            else:
                label = (
                    f"{occurrence.schedule_date} · {occurrence.definition.label} "
                    f"{occurrence.wat_at.strftime('%H:%M')} WAT — Not prepared yet"
                )
            lines.append(f"• {label}")
        recent_gemini_failures = self.store.list_retryable_gemini_failures(
            since_date=today - timedelta(days=7),
            limit=3,
        )
        if recent_gemini_failures:
            lines.extend(
                [
                    "",
                    "Held Gemini drafts (retry is available only before or during "
                    "the session):",
                ]
            )
            for post in recent_gemini_failures:
                lines.append(
                    f"• {post['schedule_date']} · {post['session_label']} — held "
                    f"({str(post.get('failure_category') or 'Gemini error').replace('_', ' ')})"
                )
                rows.append(
                    [
                        {
                            "text": (
                                f"♻️ Retry {post['session_label']} · "
                                f"{post['schedule_date']}"
                            )[:64],
                            "callback_data": (
                                f"admin:session_open:retry_generation:{post['id']}"
                            ),
                        }
                    ]
                )
        rows.append(
            [{"text": "🔙 Back to Channel Content", "callback_data": "admin:channel_posts"}]
        )
        self.api.send_message(
            chat_id,
            "\n".join(lines),
            {"inline_keyboard": rows},
        )

    def handle_callback(
        self, chat_id: int, admin_id: int, data: str, now: datetime | None = None
    ) -> bool:
        if self.admin_id is None or admin_id != self.admin_id:
            return False
        current = _as_utc(now or datetime.now(timezone.utc))
        if data == "admin:session_open:view":
            self.show_controls(chat_id, now=current)
            return True
        match = re.fullmatch(
            r"admin:session_open:(preview|approve|edit|cancel|photo|retry_generation):(\d+)",
            data,
        )
        if not match:
            return False
        action, raw_id = match.groups()
        post_id = int(raw_id)
        post = self.store.get(post_id)
        if not post:
            self.api.send_message(chat_id, "That session post is no longer available.")
            return True
        if action == "preview":
            self._show_post(chat_id, post)
        elif action == "approve":
            if self.store.update(
                post_id,
                expected=("review_pending",),
                status="approved",
                at=current.isoformat(),
            ):
                self.api.send_message(
                    chat_id,
                    "Approved. It will publish at the session open if all checks pass.",
                )
            else:
                self.api.send_message(chat_id, "This session post can no longer be approved.")
        elif action == "edit":
            if current >= self._scheduled_at(post):
                self.api.send_message(chat_id, "The session opening time has passed.")
            elif self.store.update(
                post_id,
                expected=("draft", "review_pending", "approved", "failed"),
                status="editing",
                at=current.isoformat(),
                edit_admin_id=admin_id,
                edit_previous_status=str(post["status"]),
            ):
                self.api.send_message(
                    chat_id,
                    "Send the complete replacement text now. It will be validated "
                    "before the scheduled opening. Use /cancel to keep the saved draft.",
                )
            else:
                self.api.send_message(chat_id, "This session post is no longer editable.")
        elif action == "cancel":
            if self.store.update(
                post_id,
                expected=(
                    "draft",
                    "review_pending",
                    "approved",
                    "editing",
                    "failed",
                ),
                status="cancelled",
                at=current.isoformat(),
                edit_admin_id=None,
                edit_previous_status=None,
                photo_upload_pending=0,
            ):
                self.api.send_message(chat_id, "Cancelled. This session post will not publish.")
            else:
                self.api.send_message(chat_id, "This session post can no longer be cancelled.")
        elif action == "photo":
            if current >= self._scheduled_at(post):
                self.api.send_message(chat_id, "The session opening time has passed.")
            elif self.store.update(
                post_id,
                expected=("draft", "review_pending", "approved"),
                status=str(post["status"]),
                at=current.isoformat(),
                photo_upload_pending=1,
                photo_upload_admin_id=admin_id,
            ):
                self.api.send_message(chat_id, "Send one photo in this private chat to attach it.")
            else:
                self.api.send_message(chat_id, "A photo can no longer be added to this post.")
        elif action == "retry_generation":
            self._retry_failed_generation(chat_id, post, current)
        return True

    def _retry_failed_generation(
        self, chat_id: int, post: dict[str, Any], current: datetime
    ) -> None:
        post_id = int(post["id"])
        failure_category = str(post.get("failure_category") or "")
        has_content = bool(str(post.get("content") or "").strip())
        retrying_duplicate = self._is_duplicate_retryable_failure(failure_category)
        retrying_missing_late_headline = (
            failure_category == "content_rejected_session_headline_missing"
            and bool(post.get("late_recovery"))
        )
        retrying_rejected_content = (
            retrying_duplicate or retrying_missing_late_headline
        )
        if (
            post.get("status") != "failed"
            or not (
                (
                    failure_category.startswith("gemini_")
                    and not has_content
                )
                or (retrying_rejected_content and has_content)
            )
        ):
            self.api.send_message(
                chat_id,
                "AI retry is available for an empty Gemini failure or a draft held "
                "for duplicate content/layout or a missing late-session headline. "
                "Existing content is kept unless a replacement passes every check.",
            )
            self._show_post(chat_id, post)
            return
        try:
            local_date = date.fromisoformat(str(post["schedule_date"]))
            occurrence = next(
                item
                for item in session_occurrences(local_date)
                if item.definition.code == str(post["session_code"])
            )
        except (ValueError, StopIteration):
            self.api.send_message(
                chat_id,
                "The saved session time could not be reconstructed. The post remains "
                "held and no retry was started.",
            )
            return
        late_recovery = current >= self._scheduled_at(post)
        if late_recovery:
            if current >= _session_close_utc(occurrence):
                self.api.send_message(
                    chat_id,
                    "The session has ended. Its held post remains unpublished; "
                    "no stale replacement was generated.",
                )
                self._show_post(chat_id, post)
                return
        if not self.store.update(
            post_id,
            expected=("failed",),
            status="generating",
            at=current.isoformat(),
            failure_category=None,
            retry_after_at=None,
            late_recovery=int(late_recovery),
        ):
            self.api.send_message(
                chat_id,
                "This session draft changed before retry could start. No second "
                "generation was started.",
            )
            return
        self.api.send_message(
            chat_id,
            "Retrying with the configured Gemini model. This reuses the existing "
            "session record; no channel post has been sent.",
        )
        generating = self.store.get(post_id)
        if generating is None:
            return
        self._generate(
            generating,
            occurrence,
            current,
            late_recovery=late_recovery,
            rejected_originality_draft=(
                str(post.get("content") or "") if retrying_rejected_content else None
            ),
            rejected_originality_reason=(
                (
                    "session_headline_missing"
                    if retrying_missing_late_headline
                    else failure_category.removeprefix("content_rejected_")
                )
                if retrying_rejected_content
                else None
            ),
            validation_retry=retrying_missing_late_headline,
        )
        refreshed = self.store.get(post_id)
        if refreshed is None:
            return
        if refreshed["status"] == "draft":
            if late_recovery:
                if self.store.update(
                    post_id,
                    expected=("draft",),
                    status="approved",
                    at=current.isoformat(),
                    failure_category="session_open_late_recovery",
                    late_recovery=1,
                ):
                    approved = self.store.get(post_id)
                    if approved:
                        self._publish(approved, current)
                        refreshed = self.store.get(post_id) or refreshed
                else:
                    self.api.send_message(
                        chat_id,
                        "The replacement draft changed before recovery could "
                        "publish. It remains unpublished.",
                    )
            else:
                completed_at = _as_utc(
                    datetime.fromisoformat(_utc_now())
                )
                scheduled_at = self._scheduled_at(refreshed)
                if completed_at >= scheduled_at:
                    self._hold(
                        refreshed,
                        "session_retry_review_missed",
                        "The fresh session draft finished after its scheduled opening. "
                        "It remains held and will not publish late.",
                    )
                elif scheduled_at - completed_at <= FINAL_REVIEW_LEAD:
                    self._send_review(refreshed, occurrence, completed_at)
                else:
                    self.api.send_message(
                        chat_id,
                        "Gemini retry succeeded. The draft is saved for its original "
                        "session time and will receive its scheduled private review.",
                    )
        elif refreshed["status"] == "failed":
            category = str(refreshed.get("failure_category") or "gemini_unknown")
            description = {
                "gemini_not_configured": "Gemini is not configured.",
                "gemini_rate_limit": "Gemini's request limit was reached.",
                "gemini_unexpected_error": "Gemini returned an unexpected error.",
            }.get(category, "Gemini could not generate a publishable draft.")
            if category.startswith("gemini_http_error_"):
                status = category.removeprefix("gemini_http_error_")
                description = f"Gemini's provider returned HTTP {status}."
            self.api.send_message(
                chat_id,
                f"Gemini retry failed: {description} ({category}). The same record "
                "remains held; nothing was published.",
            )
        self._show_post(chat_id, refreshed)

    def has_edit_pending(self, admin_id: int) -> bool:
        return self.admin_id == admin_id and self.store.pending_edit(admin_id) is not None

    def cancel_edit(self, admin_id: int, *, now: datetime | None = None) -> bool:
        post = self.store.pending_edit(admin_id)
        if not post:
            return False
        previous_status = str(post.get("edit_previous_status") or "review_pending")
        if previous_status not in {"draft", "review_pending", "approved", "failed"}:
            previous_status = "review_pending"
        return self.store.update(
            int(post["id"]),
            expected=("editing",),
            status=previous_status,
            at=_as_utc(now or datetime.now(timezone.utc)).isoformat(),
            edit_admin_id=None,
            edit_previous_status=None,
        )

    def handle_edit_message(
        self,
        chat_id: int,
        admin_id: int,
        is_private: bool,
        text: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        if not is_private or self.admin_id != admin_id:
            return False
        post = self.store.pending_edit(admin_id)
        if not post:
            return False
        current = _as_utc(now or datetime.now(timezone.utc))
        if current >= self._scheduled_at(post):
            self._hold(
                post,
                "session_review_edit_late",
                "The edit arrived after the session opening, so nothing was published.",
            )
            return True
        content = normalize_weekend_brand_header(text.strip(), str(post["category"]))
        rejection = validate_session_open_post(content, post)
        if not rejection and self._is_duplicate(
            content, int(post["id"]), exclude_current=True
        ):
            rejection = "duplicate_content"
        if rejection:
            self.api.send_message(
                chat_id,
                f"That edit was not saved: {rejection.replace('_', ' ')}. "
                "Send a corrected complete post, or use /cancel.",
            )
            return True
        if not self.store.update(
            int(post["id"]),
            expected=("editing",),
            status="approved",
            at=current.isoformat(),
            content=content,
            edit_admin_id=None,
            edit_previous_status=None,
        ):
            self.api.send_message(chat_id, "The session post changed; the edit was not saved.")
            return True
        self.api.send_message(
            chat_id,
            "Edit saved and validated. It will publish at the scheduled open if all final checks pass.",
        )
        return True

    def handle_admin_photo(
        self, chat_id: int, admin_id: int, photos: list[dict[str, Any]], *, is_private: bool
    ) -> bool:
        if (
            not is_private
            or self.admin_id != admin_id
            or not isinstance(photos, list)
            or not photos
        ):
            return False
        post = self.store.pending_photo(admin_id)
        if not post:
            return False
        photo = photos[-1]
        file_id = photo.get("file_id") if isinstance(photo, dict) else None
        if not isinstance(file_id, str) or not file_id:
            self.api.send_message(chat_id, "Telegram did not provide a usable photo.")
            return True
        if len(str(post["content"]).encode("utf-16-le")) // 2 > 1024:
            self.api.send_message(
                chat_id,
                "This post is too long to use as a photo caption. The saved text remains unchanged.",
            )
            return True
        changed = self.store.update(
            int(post["id"]),
            expected=("draft", "review_pending", "approved", "failed"),
            status=str(post["status"]),
            at=_utc_now(),
            photo_file_id=file_id,
            photo_upload_pending=0,
            photo_upload_admin_id=None,
        )
        if changed:
            self.api.send_message(chat_id, "Photo attached to the session post preview.")
        return True

    def _generate(
        self,
        post: dict[str, Any],
        occurrence: SessionOccurrence,
        current: datetime,
        *,
        late_recovery: bool = False,
        rejected_originality_draft: str | None = None,
        rejected_originality_reason: str | None = None,
        validation_retry: bool = False,
    ) -> None:
        if self.writer is None:
            self._hold(post, "gemini_not_configured", "Gemini is unavailable; no session post was sent.")
            return
        if self.destination_chat_id is None or int(post["destination_chat_id"]) != int(
            self.destination_chat_id
        ):
            self._hold(post, "destination_mismatch", "The saved destination does not match the configured Market Analysis channel.")
            return
        settings = self.history_store.get_channel_posting_settings()
        if settings.get("paused"):
            self._hold(post, "channel_publishing_paused", "Market Analysis publishing is paused; no post was sent.")
            return
        context = {
            "session": occurrence.definition.label,
            "session_timezone": occurrence.definition.timezone_name,
            "session_local_open": occurrence.local_at.strftime("%H:%M"),
            "session_local_close": occurrence.definition.close_time.strftime("%H:%M"),
            "session_date": occurrence.local_date.isoformat(),
            "open_time_wat": occurrence.wat_at.strftime("%H:%M WAT"),
            "late_recovery": late_recovery,
            "session_underway": late_recovery,
        }
        if rejected_originality_draft is not None:
            context = {
                **context,
                "duplicate_retry": not validation_retry,
                "validation_retry": validation_retry,
                "rejected_duplicate_draft": rejected_originality_draft[:1600],
                "originality_retry_reason": (
                    rejected_originality_reason or "duplicate_content"
                ),
                "content_retry_reason": rejected_originality_reason or "",
            }
        history = self.history_store.get_recent_channel_post_contents(
            limit=12, chat_id=self.destination_chat_id
        )
        rejected_originality_draft: str | None = None
        rejected_originality_reason: str | None = None
        rejection: str | None = None
        content = ""
        admin_feedback = self.history_store.get_recent_channel_post_feedback(limit=5)
        for attempt in range(2):
            try:
                draft = self.writer.generate(
                    schedule_date=occurrence.local_date.isoformat(),
                    schedule_time=occurrence.wat_at.strftime("%H:%M"),
                    preferred_category="new_week_preparation",
                    history=history,
                    admin_feedback=admin_feedback,
                    verified_information=[],
                    promo_due=False,
                    session_context=context,
                )
            except GeminiChannelGenerationError as error:
                if rejected_originality_draft is not None:
                    retry_cause = (rejected_originality_reason or "originality").replace(
                        "_", " "
                    )
                    self._hold(
                        post,
                        f"content_rejected_{rejected_originality_reason}_retry_{error.category}",
                        f"The prior session candidate failed {retry_cause}; its fresh "
                        f"retry failed ({error.category}). The prior candidate was "
                        "preserved for review and nothing was published.",
                        content=rejected_originality_draft,
                    )
                    return
                if error.http_status == 429:
                    reason = "Gemini's provider rate limit was reached (HTTP 429)"
                elif error.http_status is not None and 500 <= error.http_status <= 599:
                    reason = (
                        "Gemini's provider returned a temporary server error "
                        f"(HTTP {error.http_status})"
                    )
                elif error.http_status is not None:
                    reason = f"Gemini's provider returned HTTP {error.http_status}"
                else:
                    reason = error.category.replace("_", " ")
                self._hold(
                    post,
                    error.category,
                    f"Gemini could not prepare the {occurrence.definition.label} "
                    f"session post: {reason}. "
                    "It was held and not published.",
                )
                return
            except Exception:
                logger.exception(
                    "Session-open content generation failed unexpectedly."
                )
                if rejected_originality_draft is not None:
                    retry_cause = (rejected_originality_reason or "originality").replace(
                        "_", " "
                    )
                    self._hold(
                        post,
                        f"content_rejected_{rejected_originality_reason}_retry_gemini_unexpected_error",
                        f"The prior session candidate failed {retry_cause}; its fresh "
                        "retry failed unexpectedly. The prior candidate was "
                        "preserved for review and nothing was published.",
                        content=rejected_originality_draft,
                    )
                else:
                    self._hold(
                        post,
                        "gemini_unexpected_error",
                        "Gemini returned an unexpected error; the session post was held.",
                    )
                return
            content = normalize_weekend_brand_header(draft.content, draft.category)
            candidate_post = {
                **post,
                "category": draft.category,
                "content": content,
            }
            rejection = validate_session_open_post(content, candidate_post)
            if not rejection and self._is_duplicate(
                content, int(post["id"]), exclude_current=True
            ):
                rejection = "duplicate_content"
            if not rejection and self._repeats_recent_session_layout(
                content, int(post["id"])
            ):
                rejection = "repeated_session_layout"
            if rejection not in {"duplicate_content", "repeated_session_layout"} or attempt == 1:
                break
            rejected_originality_draft = content
            rejected_originality_reason = rejection
            rejected_layout = _session_layout_heading(content)
            context = {
                **context,
                "duplicate_retry": True,
                "rejected_duplicate_draft": content[:1600],
                "originality_retry_reason": rejection,
                "rejected_session_layout_heading": rejected_layout or "",
                "available_session_layout_headings": [
                    heading
                    for heading in _SESSION_LAYOUT_HEADINGS
                    if heading != rejected_layout
                ],
            }

        if rejection:
            self._hold(
                post,
                f"content_rejected_{rejection}",
                f"The {occurrence.definition.label} session post failed a content "
                f"check ({rejection.replace('_', ' ')}). It was held, not published.",
                content=content,
            )
            return
        if not self.store.update(
            int(post["id"]),
            expected=("generating",),
            status="draft",
            at=current.isoformat(),
            category=draft.category,
            content=content,
        ):
            logger.warning("Session-open draft state changed before generation could be saved.")

    def _send_review(
        self, post: dict[str, Any], occurrence: SessionOccurrence, current: datetime
    ) -> None:
        if self.admin_id is None:
            return
        post_id = int(post["id"])
        if not self.store.update(
            post_id,
            expected=("draft",),
            status="review_sending",
            at=current.isoformat(),
        ):
            return
        text = (
            "SESSION-OPEN POST REVIEW\n"
            f"Session: {occurrence.definition.label} "
            f"({occurrence.local_at.strftime('%H:%M')} "
            f"{occurrence.definition.timezone_name})\n"
            f"Destination: Market Analysis (ID {int(post['destination_chat_id'])})\n"
            f"Scheduled: {occurrence.local_date.strftime('%A, %d %B %Y')} at "
            f"{occurrence.wat_at.strftime('%H:%M')} WAT\n"
            "Review window: until the scheduled session opening.\n\n"
            f"{post['content']}\n\n"
            "Add a photo if you want; otherwise the post will be text-only. "
            "Approve, edit, or cancel. If you do not respond, an eligible post "
            "publishes automatically at the session open."
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"admin:session_open:approve:{post_id}"},
                    {"text": "✏️ Edit", "callback_data": f"admin:session_open:edit:{post_id}"},
                    {"text": "❌ Cancel", "callback_data": f"admin:session_open:cancel:{post_id}"},
                ],
                [{"text": "📷 Add photo", "callback_data": f"admin:session_open:photo:{post_id}"}],
            ]
        }
        try:
            self.api.send_message(self.admin_id, text, markup)
        except TelegramAPIError:
            self.store.update(
                post_id,
                expected=("review_sending",),
                status="failed",
                at=current.isoformat(),
                failure_category="session_review_delivery_failed",
            )
            self._notify(
                "The session-open review could not be delivered. The post is held and will not publish."
            )
            return
        self.store.update(
            post_id,
            expected=("review_sending",),
            status="review_pending",
            at=current.isoformat(),
            review_sent_at=current.isoformat(),
            review_deadline_at=occurrence.utc_at.isoformat(),
        )

    def _publish(self, post: dict[str, Any], current: datetime) -> None:
        if self.admin_id is None or self.destination_chat_id is None:
            return
        settings = self.history_store.get_channel_posting_settings()
        if settings.get("paused"):
            self._hold(post, "channel_publishing_paused", "Publishing is paused; no session post was sent.")
            return
        if int(post["destination_chat_id"]) != int(self.destination_chat_id):
            self._hold(post, "destination_mismatch", "The saved destination differs from the configured Market Analysis channel.")
            return
        content = str(post.get("content") or "")
        rejection = validate_session_open_post(content, post)
        if rejection:
            self._hold(
                post,
                rejection,
                f"The session post failed its final content check ({rejection.replace('_', ' ')}). Nothing was sent.",
            )
            return
        try:
            rendered = render_weekend_post_html(content)
            if post.get("photo_file_id") and len(content.encode("utf-16-le")) // 2 > 1024:
                raise ValueError("photo_caption_too_long")
            self.channel_post_manager.verify_destination(
                {
                    "is_promo": False,
                    "bot_username": None,
                }
            )
        except DestinationVerificationError as error:
            details = (
                f" — {error.safe_detail}"
                if error.safe_detail
                else ""
            )
            self._hold(
                post,
                error.category,
                f"Telegram/channel pre-send verification failed "
                f"({error.category.replace('_', ' ')}).{details} Nothing was sent.",
            )
            return
        except ValueError as error:
            category = str(error) if str(error) else "telegram_format_invalid"
            self._hold(
                post,
                category,
                f"Telegram/channel pre-send verification failed ({category.replace('_', ' ')}). Nothing was sent.",
            )
            return
        except TelegramAPIError:
            self._hold(
                post,
                "destination_verification_unavailable",
                "Telegram could not verify the configured Market Analysis destination and permissions. Nothing was sent.",
            )
            return
        attempts = self.store.reserve_publish(int(post["id"]), at=current.isoformat())
        if attempts is None:
            return
        try:
            if post.get("photo_file_id"):
                result = self.api.send_photo_with_result(
                    int(self.destination_chat_id),
                    str(post["photo_file_id"]),
                    caption=rendered,
                    parse_mode="HTML",
                )
            else:
                result = self.api.send_message_with_result(
                    int(self.destination_chat_id),
                    rendered,
                    parse_mode="HTML",
                )
            message_id = result.get("message_id") if isinstance(result, dict) else None
            if not isinstance(message_id, int):
                self.store.update(
                    int(post["id"]),
                    expected=("publishing",),
                    status="delivery_unknown",
                    at=current.isoformat(),
                    failure_category="telegram_confirmation_missing",
                )
                self._notify(
                    "Telegram did not confirm the session post. Delivery is uncertain; check Market Analysis before any retry."
                )
                return
            self.store.update(
                int(post["id"]),
                expected=("publishing",),
                status="published",
                at=current.isoformat(),
                telegram_message_id=message_id,
                published_at=current.isoformat(),
                failure_category=None,
            )
            self.history_store.record_channel_history_post(
                int(self.destination_chat_id),
                message_id,
                content,
                current.isoformat(),
                at=current.isoformat(),
            )
            logger.info(
                "Session-open post published session=%s date=%s message_id=%s.",
                post["session_code"],
                post["schedule_date"],
                message_id,
            )
            self._notify(
                (
                    f"A fresh {post['session_label']} session check-in was published "
                    "after the scheduled open. The public post contains no schedule time."
                    if post.get("late_recovery")
                    else f"{post['session_label']} session-open post published at "
                    f"{post['schedule_time_wat']} WAT."
                )
            )
        except TelegramAPIError as error:
            if (error.error_code == 429 or error.http_status == 429) and attempts <= MAX_RATE_LIMIT_RETRIES:
                retry_seconds = min(max(1, error.retry_after or 5), 3600)
                self.store.update(
                    int(post["id"]),
                    expected=("publishing",),
                    status="retry_wait",
                    at=current.isoformat(),
                    failure_category="telegram_rate_limit",
                    retry_after_at=(current + timedelta(seconds=retry_seconds)).isoformat(),
                )
                self._notify("Telegram rate-limited a session post. One safe retry is scheduled.")
                return
            if error.delivery_unknown or (
                error.http_status is not None and error.http_status >= 500
            ):
                status = "delivery_unknown"
                category = "telegram_delivery_unknown"
            else:
                status = "failed"
                category = (
                    "telegram_permission_error"
                    if error.error_code == 403 or error.http_status == 403
                    else "telegram_send_rejected"
                )
            self.store.update(
                int(post["id"]),
                expected=("publishing",),
                status=status,
                at=current.isoformat(),
                failure_category=category,
            )
            self._notify(
                f"The {post['session_label']} session post was not confirmed "
                f"({category.replace('_', ' ')})."
            )

    def _show_post(self, chat_id: int, post: dict[str, Any]) -> None:
        try:
            content = render_weekend_post_html(str(post["content"]))
        except ValueError:
            content = escape(str(post.get("content") or ""), quote=False)
        intro = (
            f"<b>{escape(str(post['session_label']), quote=False)} SESSION POST</b>\n"
            f"Status: {escape(str(post['status']).replace('_', ' ').title())}\n"
            f"Schedule: {escape(str(post['schedule_date']))} at "
            f"{escape(str(post['schedule_time_wat']))} WAT\n"
            f"Destination: Market Analysis (ID {int(post['destination_chat_id'])})\n\n"
        )
        post_id = int(post["id"])
        status = str(post["status"])
        failure_category = str(post.get("failure_category") or "")
        if failure_category:
            intro = intro.rstrip() + (
                f"\nFailure category: {escape(failure_category)}\n\n"
            )
        actions: list[dict[str, str]] = []
        if (
            status == "failed"
            and (
                (
                    failure_category.startswith("gemini_")
                    and not str(post.get("content") or "").strip()
                )
                or (
                    self._is_duplicate_retryable_failure(failure_category)
                    and bool(str(post.get("content") or "").strip())
                )
                or (
                    failure_category == "content_rejected_session_headline_missing"
                    and bool(post.get("late_recovery"))
                    and bool(str(post.get("content") or "").strip())
                )
            )
        ):
            actions.append(
                {
                    "text": "♻️ Retry AI draft",
                    "callback_data": (
                        f"admin:session_open:retry_generation:{post_id}"
                    ),
                }
            )
        if status == "review_pending":
            actions.append(
                {
                    "text": "✅ Approve",
                    "callback_data": f"admin:session_open:approve:{post_id}",
                }
            )
        if status in {"draft", "review_pending", "approved", "failed"} and post.get(
            "content"
        ):
            actions.append(
                {"text": "✏️ Edit", "callback_data": f"admin:session_open:edit:{post_id}"}
            )
            actions.append(
                {
                    "text": "❌ Cancel",
                    "callback_data": f"admin:session_open:cancel:{post_id}",
                }
            )
        rows = [actions] if actions else []
        if status in {"draft", "review_pending", "approved", "failed"} and post.get(
            "content"
        ):
            rows.append(
                [{"text": "📷 Add photo", "callback_data": f"admin:session_open:photo:{post_id}"}]
            )
        rows.append(
            [{"text": "🔙 Back", "callback_data": "admin:session_open:view"}]
        )
        markup = {"inline_keyboard": rows}
        self.api.send_message(chat_id, intro + content, markup, parse_mode="HTML")

    @staticmethod
    def _is_duplicate_retryable_failure(failure_category: str) -> bool:
        return any(
            failure_category.startswith(prefix)
            for prefix in _DUPLICATE_RETRYABLE_FAILURE_PREFIXES
        )

    def _is_duplicate(
        self, content: str, post_id: int, *, exclude_current: bool = False
    ) -> bool:
        candidate = _canonical(content)
        candidate_headline = _canonical(_post_headline(content))
        if not candidate:
            return True
        prior = self.history_store.get_recent_channel_post_contents(
            limit=30, chat_id=self.destination_chat_id
        )
        prior.extend(
            self.store.list_recent(
                limit=30,
                exclude_id=post_id if exclude_current else None,
            )
        )
        for item in prior:
            previous = _canonical(str(item.get("content") or ""))
            previous_headline = _canonical(
                _post_headline(str(item.get("content") or ""))
            )
            body_similarity = (
                SequenceMatcher(None, previous, candidate).ratio()
                if previous
                else 0.0
            )
            headline_similarity = (
                SequenceMatcher(None, previous_headline, candidate_headline).ratio()
                if previous_headline and candidate_headline
                else 0.0
            )
            if previous and (
                body_similarity >= 0.97
                or (headline_similarity >= 0.90 and body_similarity >= 0.85)
            ):
                return True
        return False

    def _repeats_recent_session_layout(self, content: str, post_id: int) -> bool:
        heading = _session_layout_heading(content)
        if not heading:
            return False
        recent_published = next(
            (
                item
                for item in self.store.list_recent(limit=30, exclude_id=post_id)
                if item.get("status") == "published" and item.get("content")
            ),
            None,
        )
        return bool(
            recent_published
            and _session_layout_heading(str(recent_published["content"])) == heading
        )

    def _scheduled_at(self, post: dict[str, Any]) -> datetime:
        value = datetime.fromisoformat(str(post["schedule_at_utc"]))
        return _as_utc(value)

    def _retry_due(self, post: dict[str, Any], current: datetime) -> bool:
        value = post.get("retry_after_at")
        if not value:
            return False
        try:
            return _as_utc(datetime.fromisoformat(str(value))) <= current
        except ValueError:
            return False

    def _hold(
        self,
        post: dict[str, Any],
        category: str,
        message: str,
        *,
        content: str | None = None,
    ) -> None:
        expected = (str(post["status"]),)
        fields: dict[str, Any] = {"failure_category": category}
        if content is not None:
            fields["content"] = content
        if not self.store.update(
            int(post["id"]),
            expected=expected,
            status="failed",
            at=_utc_now(),
            **fields,
        ):
            return
        logger.warning(
            "Session-open post held session=%s date=%s category=%s.",
            post.get("session_code"),
            post.get("schedule_date"),
            category,
        )
        retry_markup = None
        if category.startswith("gemini_") and not str(
            post.get("content") or ""
        ).strip():
            retry_markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": "♻️ Retry AI draft",
                            "callback_data": (
                                "admin:session_open:retry_generation:"
                                f"{int(post['id'])}"
                            ),
                        }
                    ]
                ]
            }
        self._notify(message, reply_markup=retry_markup)

    def _notify_recovery(self) -> None:
        for item in self.store.recovery_events:
            if item["status"] == "delivery_unknown":
                message = (
                    f"Delivery of the {item['session_label']} session post on "
                    f"{item['schedule_date']} is uncertain after restart. Check the "
                    "Market Analysis channel before retrying; it was not resent."
                )
            else:
                message = (
                    f"The {item['session_label']} session post on "
                    f"{item['schedule_date']} was held after restart "
                    f"({item['failure_category'].replace('_', ' ')})."
                )
            self._notify(message)

    def _notify(
        self,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        if self.admin_id is None:
            return
        try:
            self.api.send_message(
                self.admin_id,
                text,
                reply_markup=reply_markup,
            )
        except TelegramAPIError:
            logger.warning("Could not privately notify the administrator about a session post.")


def _canonical(text: str) -> str:
    text = re.sub(r"no confirmation,\s*no entry\.?", "", text.casefold())
    return _CANONICAL.sub("", text)


def _post_headline(content: str) -> str:
    lines = [line.strip() for line in content.splitlines()]
    for index, line in enumerate(lines):
        if "━" in line:
            return next((item for item in lines[index + 1 :] if item), "")
    return next((item for item in lines if item), "")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
