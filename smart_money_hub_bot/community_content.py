"""Draft-only community content manager with an explicit, persistent schedule."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, time as ClockTime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .channel_gemini import (
    GeminiChannelContentService,
    GeminiChannelGenerationError,
)
from .trade_ledger import TradeLedger
from .telegram_api import TelegramAPIError

CONTENT_CATEGORIES = (
    "good_morning",
    "daily_motivation",
    "session_update",
    "trading_day_open",
    "end_of_day",
    "friday_recap",
    "weekend_message",
    "sunday_preparation",
    "weekly_results",
    "successful_trade_recap",
    "loss_lesson",
    "educational_reminder",
    "smc_quiz",
    "premium_invitation",
    "milestone",
    "community_engagement",
    "discipline_reminder",
)

_WRITER_CATEGORY = {
    "good_morning": "engagement",
    "daily_motivation": "trading_psychology",
    "session_update": "new_week_preparation",
    "trading_day_open": "new_week_preparation",
    "end_of_day": "weekly_market_recap",
    "friday_recap": "weekly_market_recap",
    "weekend_message": "engagement",
    "sunday_preparation": "new_week_preparation",
    "educational_reminder": "education",
    "smc_quiz": "engagement",
    "community_engagement": "engagement",
    "discipline_reminder": "risk_management",
}

_PROMISES = re.compile(
    r"\b(?:guaranteed\s+(?:profit|returns?)|risk[- ]free|"
    r"100\s*%\s*(?:win|success)|buy\s+now|sell\s+now)\b",
    re.IGNORECASE,
)
_HEADER_LINE = re.compile(r"^(?:[\U0001f000-\U0001faff]\ufe0f?\s*)?SMART MONEY HUB\b")
_HEADING_LINE = re.compile(
    r"^(?:[A-Z][A-Z0-9 /&'’:-]{2,80}|"
    r"(?:📚|📊|🔍|🧠|🎯|🛡️|⚠️|✅|💬|💧|📌|🤖)\s+[A-Z0-9][A-Z0-9 /&'’:-]{2,80})$"
)
_MAX_MESSAGE_UTF16 = 4096
_WAT = ZoneInfo("Africa/Lagos")


class CommunityContentError(ValueError):
    """Safe error for invalid content, schedules, or state transitions."""


def render_telegram_html(content: str) -> str:
    """Escape plain text and bold the brand header and recognizable headings."""
    lines = str(content).splitlines()
    rendered: list[str] = []
    for index, line in enumerate(lines):
        escaped = html.escape(line, quote=True)
        if index == 0 and _HEADER_LINE.match(line.strip()):
            escaped = f"<b>{escaped}</b>"
        elif _HEADING_LINE.fullmatch(line.strip()):
            escaped = f"<b>{escaped}</b>"
        rendered.append(escaped)
    result = "\n".join(rendered)
    if len(result.encode("utf-16-le")) // 2 > _MAX_MESSAGE_UTF16:
        raise CommunityContentError("Content exceeds Telegram's 4096-character limit.")
    return result


class CommunityContentRepository:
    """SQLite persistence for drafts, admin feedback, schedule and idempotency."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS smh_content_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                INSERT OR IGNORE INTO smh_content_settings
                    (setting_key, setting_value, updated_at_utc)
                    VALUES ('enabled', '0', '1970-01-01T00:00:00+00:00');
                INSERT OR IGNORE INTO smh_content_settings
                    (setting_key, setting_value, updated_at_utc)
                    VALUES ('auto_publish_enabled', '0', '1970-01-01T00:00:00+00:00');
                CREATE TABLE IF NOT EXISTS smh_content_drafts (
                    draft_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    destination_chat_id INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'draft', 'approved', 'rejected', 'publishing',
                        'published', 'failed', 'delivery_unknown'
                    )),
                    content_source TEXT NOT NULL,
                    source_trade_ids_json TEXT NOT NULL DEFAULT '[]',
                    stats_period_start TEXT,
                    stats_period_end TEXT,
                    rejection_reason TEXT,
                    failure_category TEXT,
                    approving_admin_id INTEGER,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    approved_at_utc TEXT,
                    published_at_utc TEXT,
                    telegram_message_id INTEGER,
                    content_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS smh_content_drafts_history
                    ON smh_content_drafts(created_at_utc DESC, category, status);
                CREATE TABLE IF NOT EXISTS smh_content_feedback (
                    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT NOT NULL REFERENCES smh_content_drafts(draft_id),
                    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'edited', 'rejected')),
                    details TEXT NOT NULL DEFAULT '',
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS smh_content_draft_versions (
                    draft_id TEXT NOT NULL REFERENCES smh_content_drafts(draft_id),
                    revision INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_source TEXT NOT NULL,
                    saved_at_utc TEXT NOT NULL,
                    PRIMARY KEY (draft_id, revision)
                );
                CREATE TABLE IF NOT EXISTS smh_content_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    destination_chat_id INTEGER NOT NULL,
                    timezone_name TEXT NOT NULL,
                    local_time TEXT NOT NULL,
                    frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly')),
                    weekday INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
                    approval_mode TEXT NOT NULL DEFAULT 'manual'
                        CHECK (approval_mode IN ('manual', 'auto')),
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS smh_content_schedule_runs (
                    schedule_id TEXT NOT NULL REFERENCES smh_content_schedules(schedule_id),
                    local_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN (
                        'reserved', 'draft_created', 'failed', 'delivery_unknown'
                    )),
                    draft_id TEXT,
                    failure_category TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    PRIMARY KEY (schedule_id, local_date)
                );
                CREATE TABLE IF NOT EXISTS smh_content_publication_log (
                    publication_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT NOT NULL UNIQUE REFERENCES smh_content_drafts(draft_id),
                    destination_chat_id INTEGER NOT NULL,
                    telegram_message_id INTEGER,
                    status TEXT NOT NULL,
                    published_at_utc TEXT,
                    failure_category TEXT
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _utc(value: datetime | None = None) -> str:
        observed = value or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            raise CommunityContentError("A timezone-aware timestamp is required.")
        return observed.astimezone(timezone.utc).isoformat(timespec="seconds")

    def enabled(self) -> bool:
        return self.setting("enabled") == "1"

    def set_enabled(self, enabled: bool, *, now: datetime | None = None) -> None:
        self.set_setting("enabled", "1" if enabled else "0", now=now)

    def set_setting(
        self, key: str, value: str, *, now: datetime | None = None
    ) -> None:
        if key not in {"enabled", "auto_publish_enabled"}:
            raise CommunityContentError("Unsupported content setting.")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO smh_content_settings VALUES (?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (key, value, self._utc(now)),
            )

    def setting(self, key: str) -> str:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT setting_value FROM smh_content_settings WHERE setting_key=?",
                (key,),
            ).fetchone()
        return str(row["setting_value"]) if row else "0"

    def create_draft(
        self,
        *,
        category: str,
        content: str,
        destination_chat_id: int,
        content_source: str,
        source_trade_ids: list[str] | None = None,
        stats_period_start: str | None = None,
        stats_period_end: str | None = None,
        now: datetime | None = None,
    ) -> str:
        normalized = str(content).strip()
        if category not in CONTENT_CATEGORIES:
            raise CommunityContentError("Choose a supported content category.")
        if not normalized:
            raise CommunityContentError("A blank draft cannot be saved.")
        if _PROMISES.search(normalized):
            raise CommunityContentError(
                "The draft contains a prohibited trading promise or signal phrase."
            )
        render_telegram_html(normalized)
        observed = self._utc(now)
        content_hash = hashlib.sha256(
            f"{category}\0{destination_chat_id}\0{normalized}".encode("utf-8")
        ).hexdigest()
        draft_id = uuid.uuid4().hex[:12].upper()
        with closing(self._connect()) as connection, connection:
            duplicate = connection.execute(
                "SELECT draft_id FROM smh_content_drafts WHERE content_hash=? "
                "AND status NOT IN ('rejected', 'failed')",
                (content_hash,),
            ).fetchone()
            if duplicate:
                return str(duplicate["draft_id"])
            connection.execute(
                """
                INSERT INTO smh_content_drafts (
                    draft_id, category, content, destination_chat_id, status,
                    content_source, source_trade_ids_json, stats_period_start,
                    stats_period_end, created_at_utc, updated_at_utc, content_hash
                ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    category,
                    normalized,
                    int(destination_chat_id),
                    content_source,
                    json.dumps(source_trade_ids or []),
                    stats_period_start,
                    stats_period_end,
                    observed,
                    observed,
                    content_hash,
                ),
            )
        return draft_id

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM smh_content_drafts WHERE draft_id=?",
                (draft_id.strip().upper(),),
            ).fetchone()
        return self._dict(row)

    def list_drafts(
        self, *, limit: int = 20, statuses: tuple[str, ...] | None = None
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 100)
        where = ""
        params: list[Any] = []
        if statuses:
            where = "WHERE status IN (" + ",".join("?" for _ in statuses) + ")"
            params.extend(statuses)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM smh_content_drafts {where} "
                "ORDER BY created_at_utc DESC LIMIT ?",
                (*params, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def edit_draft(
        self, draft_id: str, content: str, *, now: datetime | None = None
    ) -> None:
        normalized = str(content).strip()
        if not normalized or _PROMISES.search(normalized):
            raise CommunityContentError("The edited draft is blank or unsafe.")
        render_telegram_html(normalized)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM smh_content_drafts WHERE draft_id=?",
                (draft_id.strip().upper(),),
            ).fetchone()
            if not row:
                raise CommunityContentError("Draft not found.")
            if row["status"] not in {"draft", "approved"}:
                raise CommunityContentError("Only an unpublished draft can be edited.")
            connection.execute(
                """
                INSERT OR IGNORE INTO smh_content_draft_versions (
                    draft_id, revision, content, content_source, saved_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    draft_id.strip().upper(),
                    row["revision"],
                    row["content"],
                    row["content_source"],
                    self._utc(now),
                ),
            )
            digest = hashlib.sha256(
                f"{row['category']}\0{row['destination_chat_id']}\0{normalized}".encode()
            ).hexdigest()
            connection.execute(
                """
                UPDATE smh_content_drafts SET content=?, status='draft',
                    content_source='admin_edited', content_hash=?,
                    revision=revision+1, approving_admin_id=NULL,
                    approved_at_utc=NULL, updated_at_utc=?
                WHERE draft_id=?
                """,
                (normalized, digest, self._utc(now), draft_id.strip().upper()),
            )
            connection.execute(
                """
                INSERT INTO smh_content_feedback (draft_id, decision, details, created_at_utc)
                VALUES (?, 'edited', ?, ?)
                """,
                (draft_id.strip().upper(), "Administrator edited the draft.", self._utc(now)),
            )

    def reserve_publication(
        self,
        draft_id: str,
        *,
        destination_chat_id: int,
        now: datetime,
    ) -> bool:
        identifier = draft_id.strip().upper()
        observed = self._utc(now)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE smh_content_drafts SET status='publishing',
                    updated_at_utc=?
                WHERE draft_id=? AND status='approved'
                    AND destination_chat_id=?
                """,
                (observed, identifier, int(destination_chat_id)),
            )
            if cursor.rowcount != 1:
                return False
            try:
                connection.execute(
                    """
                    INSERT INTO smh_content_publication_log (
                        draft_id, destination_chat_id, status
                    ) VALUES (?, ?, 'publishing')
                    """,
                    (identifier, int(destination_chat_id)),
                )
            except sqlite3.IntegrityError:
                connection.execute(
                    "UPDATE smh_content_drafts SET status='delivery_unknown', "
                    "failure_category='previous_publication_attempt' WHERE draft_id=?",
                    (identifier,),
                )
                return False
        return True

    def finish_publication(
        self,
        draft_id: str,
        *,
        status: str,
        message_id: int | None = None,
        failure_category: str | None = None,
        now: datetime,
    ) -> None:
        if status not in {"published", "failed", "delivery_unknown"}:
            raise CommunityContentError("Unsupported publication result.")
        observed = self._utc(now)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE smh_content_drafts SET status=?, failure_category=?,
                    telegram_message_id=?, published_at_utc=?,
                    updated_at_utc=?
                WHERE draft_id=? AND status='publishing'
                """,
                (
                    status,
                    failure_category,
                    message_id,
                    observed if status == "published" else None,
                    observed,
                    draft_id.strip().upper(),
                ),
            )
            connection.execute(
                """
                UPDATE smh_content_publication_log SET status=?,
                    telegram_message_id=?, published_at_utc=?, failure_category=?
                WHERE draft_id=?
                """,
                (
                    status,
                    message_id,
                    observed if status == "published" else None,
                    failure_category,
                    draft_id.strip().upper(),
                ),
            )

    def publication_started(self, draft_id: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM smh_content_publication_log WHERE draft_id=?",
                (draft_id.strip().upper(),),
            ).fetchone()
        return bool(row)

    def mark_interrupted_publications(self, *, now: datetime | None = None) -> int:
        """Prevent a restart from blindly retrying a send with unknown delivery."""
        observed = self._utc(now)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT draft_id FROM smh_content_drafts WHERE status='publishing'"
            ).fetchall()
            for row in rows:
                identifier = row["draft_id"]
                connection.execute(
                    """
                    UPDATE smh_content_drafts SET status='delivery_unknown',
                        failure_category='process_restarted_during_send',
                        updated_at_utc=? WHERE draft_id=? AND status='publishing'
                    """,
                    (observed, identifier),
                )
                connection.execute(
                    """
                    UPDATE smh_content_publication_log SET
                        status='delivery_unknown',
                        failure_category='process_restarted_during_send'
                    WHERE draft_id=? AND status='publishing'
                    """,
                    (identifier,),
                )
        return len(rows)

    def decide(
        self,
        draft_id: str,
        decision: str,
        *,
        admin_id: int,
        reason: str = "",
        now: datetime | None = None,
    ) -> None:
        if decision not in {"approved", "rejected"}:
            raise CommunityContentError("Decision must be approve or reject.")
        identifier = draft_id.strip().upper()
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM smh_content_drafts WHERE draft_id=?", (identifier,)
            ).fetchone()
            if not row:
                raise CommunityContentError("Draft not found.")
            if row["status"] != "draft":
                raise CommunityContentError("Only an unreviewed draft can be decided.")
            if decision == "rejected" and not reason.strip():
                raise CommunityContentError("Add a short rejection reason.")
            observed = self._utc(now)
            connection.execute(
                """
                UPDATE smh_content_drafts SET status=?, rejection_reason=?,
                    approving_admin_id=?, approved_at_utc=?, updated_at_utc=?
                WHERE draft_id=? AND status='draft'
                """,
                (
                    decision,
                    reason.strip()[:500] if decision == "rejected" else None,
                    admin_id if decision == "approved" else None,
                    observed if decision == "approved" else None,
                    observed,
                    identifier,
                ),
            )
            connection.execute(
                """
                INSERT INTO smh_content_feedback (draft_id, decision, details, created_at_utc)
                VALUES (?, ?, ?, ?)
                """,
                (
                    identifier,
                    "accepted" if decision == "approved" else "rejected",
                    reason.strip()[:500],
                    observed,
                ),
            )

    def save_schedule(
        self,
        *,
        schedule_id: str,
        category: str,
        destination_chat_id: int,
        timezone_name: str,
        local_time: str,
        frequency: str,
        weekday: int | None = None,
        enabled: bool = False,
        now: datetime | None = None,
    ) -> None:
        if category not in CONTENT_CATEGORIES:
            raise CommunityContentError("Choose a supported content category.")
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise CommunityContentError("Choose a valid IANA timezone.") from None
        try:
            parsed_time = ClockTime.fromisoformat(local_time)
        except ValueError:
            raise CommunityContentError("Use a 24-hour time such as 08:00.") from None
        if parsed_time.tzinfo is not None:
            raise CommunityContentError("Schedule time must be local wall time.")
        if frequency not in {"daily", "weekly"}:
            raise CommunityContentError("Frequency must be daily or weekly.")
        if frequency == "weekly" and (
            weekday is None or isinstance(weekday, bool) or not 0 <= weekday <= 6
        ):
            raise CommunityContentError("A weekly schedule needs weekday 0–6.")
        if frequency == "daily":
            weekday = None
        observed = self._utc(now)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO smh_content_schedules (
                    schedule_id, category, destination_chat_id, timezone_name,
                    local_time, frequency, weekday, enabled, approval_mode,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    category=excluded.category,
                    destination_chat_id=excluded.destination_chat_id,
                    timezone_name=excluded.timezone_name,
                    local_time=excluded.local_time,
                    frequency=excluded.frequency,
                    weekday=excluded.weekday,
                    enabled=excluded.enabled,
                    approval_mode='manual',
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    schedule_id.strip()[:80],
                    category,
                    int(destination_chat_id),
                    timezone_name,
                    parsed_time.isoformat(timespec="minutes"),
                    frequency,
                    weekday,
                    int(enabled),
                    observed,
                    observed,
                ),
            )

    def list_schedules(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM smh_content_schedules ORDER BY local_time, schedule_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def reserve_schedule_run(
        self, schedule_id: str, local_date: date, *, now: datetime
    ) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO smh_content_schedule_runs (
                    schedule_id, local_date, status, created_at_utc, updated_at_utc
                ) VALUES (?, ?, 'reserved', ?, ?)
                """,
                (schedule_id, local_date.isoformat(), self._utc(now), self._utc(now)),
            )
        return cursor.rowcount == 1

    def finish_schedule_run(
        self,
        schedule_id: str,
        local_date: date,
        *,
        status: str,
        draft_id: str | None = None,
        failure_category: str | None = None,
        now: datetime,
    ) -> None:
        if status not in {"draft_created", "failed", "delivery_unknown"}:
            raise CommunityContentError("Unsupported scheduled-run status.")
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE smh_content_schedule_runs SET status=?, draft_id=?,
                    failure_category=?, updated_at_utc=?
                WHERE schedule_id=? AND local_date=?
                """,
                (
                    status,
                    draft_id,
                    failure_category,
                    self._utc(now),
                    schedule_id,
                    local_date.isoformat(),
                ),
            )

    def recent_feedback(self, *, limit: int = 5) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT f.decision, f.details, d.category, d.created_at_utc
                FROM smh_content_feedback f
                JOIN smh_content_drafts d ON d.draft_id=f.draft_id
                ORDER BY f.feedback_id DESC LIMIT ?
                """,
                (min(max(int(limit), 1), 20),),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row else None


class CommunityContentManager:
    """Creates reviewable drafts; no scheduler path publishes automatically."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        writer: GeminiChannelContentService | None = None,
        trade_ledger: TradeLedger | None = None,
        allowed_destinations: set[int] | dict[int, str] | None = None,
    ) -> None:
        self.repository = CommunityContentRepository(database_path)
        self.writer = writer
        self.trade_ledger = trade_ledger or TradeLedger(database_path)
        if isinstance(allowed_destinations, dict):
            self.allowed_destination_types = {
                int(chat_id): str(chat_type)
                for chat_id, chat_type in allowed_destinations.items()
            }
        else:
            self.allowed_destination_types = {
                int(chat_id): "unknown" for chat_id in (allowed_destinations or set())
            }
        self.allowed_destinations = set(self.allowed_destination_types)
        self.repository.mark_interrupted_publications()

    def generate_draft(
        self,
        category: str,
        destination_chat_id: int,
        *,
        now: datetime | None = None,
        verified_information: list[str] | None = None,
        trade_id: str | None = None,
        stats_start: date | None = None,
        stats_end: date | None = None,
    ) -> str:
        if int(destination_chat_id) not in self.allowed_destinations:
            raise CommunityContentError(
                "Select an explicitly configured destination; arbitrary chats are blocked."
            )
        if category not in CONTENT_CATEGORIES:
            raise CommunityContentError("Choose a supported content category.")
        if category == "premium_invitation":
            raise CommunityContentError(
                "Premium-access policy and invitation link are not verified."
            )
        if category in {"weekly_results", "milestone"}:
            content, trade_ids = self._statistics_content(
                category, stats_start=stats_start, stats_end=stats_end
            )
            return self.repository.create_draft(
                category=category,
                content=content,
                destination_chat_id=destination_chat_id,
                content_source="verified_trade_ledger_template",
                source_trade_ids=trade_ids,
                stats_period_start=stats_start.isoformat() if stats_start else None,
                stats_period_end=stats_end.isoformat() if stats_end else None,
                now=now,
            )
        if category == "successful_trade_recap":
            content, trade_ids = self._successful_trade_content(trade_id)
            return self.repository.create_draft(
                category=category,
                content=content,
                destination_chat_id=destination_chat_id,
                content_source="verified_trade_ledger_template",
                source_trade_ids=trade_ids,
                now=now,
            )
        if category == "loss_lesson":
            content, trade_ids = self._loss_lesson_content(trade_id)
            return self.repository.create_draft(
                category=category,
                content=content,
                destination_chat_id=destination_chat_id,
                content_source="verified_trade_ledger_template",
                source_trade_ids=trade_ids,
                now=now,
            )

        writer_category = _WRITER_CATEGORY.get(category)
        if writer_category is None:
            raise CommunityContentError("No safe generator is configured for that category.")
        current = now or datetime.now(timezone.utc)
        history = self.repository.list_drafts(limit=12)
        feedback = self.repository.recent_feedback(limit=5)
        content_source = "gemini"
        if self.writer is None:
            raise CommunityContentError(
                "Gemini drafting is not configured; no draft was created."
            )
        try:
            generated = self.writer.generate(
                schedule_date=current.astimezone(_WAT).date().isoformat(),
                schedule_time=current.astimezone(_WAT).strftime("%H:%M WAT"),
                preferred_category=writer_category,
                history=history,
                admin_feedback=feedback,
                verified_information=verified_information or [],
                promo_due=False,
                promo_username=None,
            )
        except GeminiChannelGenerationError as error:
            category_name = re.sub(r"[^a-z0-9_]", "", error.category.casefold())[:60]
            raise CommunityContentError(
                f"Gemini drafting failed ({category_name or 'provider_error'}); "
                "no draft was saved."
            ) from None
        content = generated.content
        return self.repository.create_draft(
            category=category,
            content=content,
            destination_chat_id=destination_chat_id,
            content_source=content_source,
            now=current,
        )

    def _statistics_content(
        self, category: str, *, stats_start: date | None, stats_end: date | None
    ) -> tuple[str, list[str]]:
        stats = self.trade_ledger.calculate_statistics(
            start=stats_start, end=stats_end
        )
        sample = int(stats["verified_closed_sample"])
        if sample <= 0:
            raise CommunityContentError(
                "No verified closed trades exist for that period; no results draft was made."
            )
        period = (
            f"{stats_start.isoformat()} to {stats_end.isoformat()}"
            if stats_start and stats_end
            else "All recorded dates"
        )
        lines = [
            "📊 SMART MONEY HUB",
            "",
            "WEEKLY RESULTS — VERIFIED LEDGER SUMMARY"
            if category == "weekly_results"
            else "TRADING MILESTONE — VERIFIED LEDGER SUMMARY",
            "",
            f"Period: {period}",
            f"Verified closed trades: {sample}",
            (
                f"Wins: {stats['wins']} · Losses: {stats['losses']} · "
                f"Breakeven: {stats['breakeven']}"
            ),
            (
                f"Win rate: {stats['win_rate']}% "
                f"(wins ÷ wins + losses; breakeven excluded)"
                if stats["win_rate"] is not None
                else "Win rate: Unavailable (no decisive closed trades)"
            ),
        ]
        for summary in stats["net_pips_by_instrument_and_convention"].values():
            lines.append(
                f"Net pips for {summary['instrument']} "
                f"(pip size {summary['pip_size']}): {summary['net']} "
                f"(sample {summary['sample_size']})"
            )
        for currency, result in stats["realized_pl_by_currency"].items():
            lines.append(
                f"Recorded net P/L: {result['net']} {currency} "
                f"(verified monetary entries: {result['sample_size']})"
            )
        lines.extend(
            [
                "",
                "Only verified closed records are included. Unverified records "
                f"excluded: {stats['unverified_closed_excluded']}.",
                "Results describe this ledger sample and do not predict future performance.",
                "NO CONFIRMATION, NO ENTRY.",
            ]
        )
        trade_ids = [
            row["trade_id"]
            for row in self.trade_ledger.list_trades(
                start=stats_start, end=stats_end, limit=500
            )
            if row["verification_status"] == "verified"
            and row["status"] == "closed"
            and row["outcome"] in {"win", "loss", "breakeven"}
        ]
        return "\n".join(lines), trade_ids

    def _successful_trade_content(self, trade_id: str | None) -> tuple[str, list[str]]:
        trade = self.trade_ledger.get_trade(str(trade_id or ""))
        if (
            not trade
            or trade["verification_status"] != "verified"
            or trade["status"] != "closed"
            or trade["outcome"] != "win"
        ):
            raise CommunityContentError(
                "A successful-trade draft requires one verified closed winning record."
            )
        details = [
            "🎯 SMART MONEY HUB",
            "",
            "VERIFIED TRADE REVIEW",
            "",
            f"Instrument: {trade['instrument']}",
            f"Outcome: {trade['outcome'].upper()}",
            f"Period: {trade['opened_at_utc'][:10]}",
        ]
        if trade["net_pips"] is not None:
            details.append(
                f"Recorded net pips: {trade['net_pips']} "
                f"(pip size {trade['pip_size']})"
            )
        if trade["realized_pl"] is not None:
            details.append(
                f"Recorded realized result: {trade['realized_pl']} {trade['currency']}"
            )
        details.extend(
            [
                "",
                "This single verified record is not a promise or typical-results claim.",
                "NO CONFIRMATION, NO ENTRY.",
            ]
        )
        return "\n".join(details), [str(trade["trade_id"])]

    def _loss_lesson_content(self, trade_id: str | None) -> tuple[str, list[str]]:
        trade = self.trade_ledger.get_trade(str(trade_id or ""))
        if (
            not trade
            or trade["verification_status"] != "verified"
            or trade["status"] != "closed"
            or trade["outcome"] != "loss"
        ):
            raise CommunityContentError(
                "A loss lesson requires one verified closed losing record."
            )
        return (
            "\n".join(
                [
                    "🧠 SMART MONEY HUB",
                    "",
                    "LESSON FROM A VERIFIED TRADE REVIEW",
                    "",
                    f"Instrument: {trade['instrument']}",
                    f"Period: {trade['opened_at_utc'][:10]}",
                    "A losing result is not, by itself, proof of a bad decision. "
                    "Review the recorded setup, confirmation, invalidation, and risk "
                    "plan before deciding what to change.",
                    "",
                    "NO CONFIRMATION, NO ENTRY.",
                ]
            ),
            [str(trade["trade_id"])],
        )

    def save_schedule(
        self,
        *,
        schedule_id: str,
        category: str,
        destination_chat_id: int,
        timezone_name: str,
        local_time: str,
        frequency: str,
        weekday: int | None = None,
        enabled: bool = False,
        now: datetime | None = None,
    ) -> None:
        if int(destination_chat_id) not in self.allowed_destinations:
            raise CommunityContentError(
                "Only explicitly configured Education-group or Market Analysis destinations are allowed."
            )
        self.repository.save_schedule(
            schedule_id=schedule_id,
            category=category,
            destination_chat_id=destination_chat_id,
            timezone_name=timezone_name,
            local_time=local_time,
            frequency=frequency,
            weekday=weekday,
            enabled=enabled,
            now=now,
        )

    def publish_approved(
        self,
        draft_id: str,
        *,
        admin_id: int,
        api: Any,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Publish only after explicit approval and a fresh destination check."""
        identifier = draft_id.strip().upper()
        draft = self.repository.get_draft(identifier)
        if not draft:
            raise CommunityContentError("Draft not found.")
        if draft["status"] != "approved":
            raise CommunityContentError(
                "Only an explicitly approved draft can be published."
            )
        destination = int(draft["destination_chat_id"])
        expected_type = self.allowed_destination_types.get(destination)
        if expected_type is None:
            raise CommunityContentError("The draft destination is not allowlisted.")
        if _PROMISES.search(draft["content"]):
            raise CommunityContentError(
                "The draft now fails a publishing safety check; it was not sent."
            )
        html_text = render_telegram_html(draft["content"])
        try:
            chat = api.get_chat(destination)
            if not isinstance(chat, dict) or int(chat.get("id", 0)) != destination:
                raise CommunityContentError(
                    "Telegram destination verification did not match the configured ID."
                )
            chat_type = str(chat.get("type", ""))
            if expected_type != "unknown" and chat_type != expected_type:
                raise CommunityContentError(
                    "Telegram destination type does not match the configured destination."
                )
            bot_id = int(api.get_me().get("id", 0))
            if bot_id <= 0:
                raise CommunityContentError("Telegram did not verify the bot identity.")
            member = api.get_chat_member(destination, bot_id)
        except TelegramAPIError as error:
            category = (
                f"telegram_http_{error.http_status}"
                if error.http_status
                else "telegram_destination_api_error"
            )
            raise CommunityContentError(
                f"Destination or permission check failed ({category}); no post was sent."
            ) from None
        status = str(member.get("status", "")) if isinstance(member, dict) else ""
        if status not in {"administrator", "creator"}:
            raise CommunityContentError(
                "The bot is not an administrator of the configured destination."
            )
        if chat_type == "channel" and member.get("can_post_messages") is False:
            raise CommunityContentError(
                "Telegram confirms the bot cannot publish in this channel."
            )
        if chat_type in {"group", "supergroup"} and member.get("can_send_messages") is False:
            raise CommunityContentError(
                "Telegram confirms the bot cannot send messages in this group."
            )
        current = now or datetime.now(timezone.utc)
        if not self.repository.reserve_publication(
            identifier, destination_chat_id=destination, now=current
        ):
            raise CommunityContentError(
                "This draft is not publishable or already has a send attempt. "
                "Check its publication status before retrying."
            )
        try:
            result = api.send_message_with_result(
                destination,
                html_text,
                parse_mode="HTML",
            )
        except TelegramAPIError as error:
            category = (
                "telegram_delivery_unknown"
                if error.delivery_unknown
                else f"telegram_http_{error.http_status or error.error_code or 'error'}"
            )
            final_status = "delivery_unknown" if error.delivery_unknown else "failed"
            self.repository.finish_publication(
                identifier,
                status=final_status,
                failure_category=category,
                now=current,
            )
            raise CommunityContentError(
                f"Telegram send failed ({category}). "
                + (
                    "Check the destination before any manual retry."
                    if error.delivery_unknown
                    else "The draft remains saved; it was not retried."
                )
            ) from None
        except Exception:
            self.repository.finish_publication(
                identifier,
                status="delivery_unknown",
                failure_category="telegram_send_unexpected_error",
                now=current,
            )
            raise CommunityContentError(
                "Telegram send outcome is unknown. Check the destination before retrying."
            ) from None
        # Telegram's sendMessage result is the Message object itself, including
        # its message_id at the top level.
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int):
            self.repository.finish_publication(
                identifier,
                status="delivery_unknown",
                failure_category="telegram_message_id_missing",
                now=current,
            )
            raise CommunityContentError(
                "Telegram returned no message ID. Check the destination before retrying."
            )
        self.repository.finish_publication(
            identifier,
            status="published",
            message_id=message_id,
            now=current,
        )
        return {
            "draft_id": identifier,
            "destination_chat_id": destination,
            "telegram_message_id": message_id,
            "published_at_utc": CommunityContentRepository._utc(current),
        }

    def dispatch_due(
        self,
        *,
        now: datetime | None = None,
        notify_admin: Any | None = None,
    ) -> None:
        """Create due drafts only; this scheduler never publishes them."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("Scheduler time must be timezone-aware.")
        if not self.repository.enabled():
            return
        for schedule in self.repository.list_schedules():
            if not schedule["enabled"]:
                continue
            try:
                zone = ZoneInfo(schedule["timezone_name"])
                local_now = current.astimezone(zone)
                scheduled_time = ClockTime.fromisoformat(schedule["local_time"])
            except (ZoneInfoNotFoundError, ValueError):
                continue
            if schedule["frequency"] == "weekly" and local_now.weekday() != schedule["weekday"]:
                continue
            due_at = datetime.combine(local_now.date(), scheduled_time, zone)
            if local_now < due_at or local_now - due_at > timedelta(minutes=5):
                continue
            local_date = local_now.date()
            if not self.repository.reserve_schedule_run(
                schedule["schedule_id"], local_date, now=current
            ):
                continue
            try:
                draft_id = self.generate_draft(
                    schedule["category"],
                    int(schedule["destination_chat_id"]),
                    now=current,
                )
                self.repository.finish_schedule_run(
                    schedule["schedule_id"],
                    local_date,
                    status="draft_created",
                    draft_id=draft_id,
                    now=current,
                )
                if notify_admin:
                    notify_admin(
                        f"A scheduled {schedule['category']} draft is ready for review "
                        f"(ID {draft_id}). It has not been published."
                    )
            except CommunityContentError:
                self.repository.finish_schedule_run(
                    schedule["schedule_id"],
                    local_date,
                    status="failed",
                    failure_category="draft_generation_failed",
                    now=current,
                )
                if notify_admin:
                    notify_admin(
                        f"The scheduled {schedule['category']} draft could not be "
                        "created safely. No post was published."
                    )

