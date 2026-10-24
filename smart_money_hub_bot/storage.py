"""SQLite repository for members, assessments, journals, progress, and reminders."""

import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .knowledge_approval import can_approve, rejection_status
from .knowledge_base import find_similar_item
from .knowledge_versions import next_version_number
from .scoring import AssessmentResult


DEFAULT_DATABASE_PATH = Path("data/smart_money_hub.sqlite3")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repository:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        telegram_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        chat_id INTEGER,
                        is_private INTEGER NOT NULL DEFAULT 0,
                        started_at TEXT NOT NULL,
                        last_interaction_at TEXT NOT NULL,
                        last_checkin_at TEXT,
                        reminders_enabled INTEGER NOT NULL DEFAULT 0,
                        zoom_class_reminders_enabled INTEGER NOT NULL DEFAULT 0,
                        reminders_stopped INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS bot_runtime_state (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        last_successful_poll_at TEXT,
                        last_recovery_at TEXT,
                        last_recovery_gap_seconds INTEGER
                    );

                    INSERT OR IGNORE INTO bot_runtime_state (id)
                    VALUES (1);

                    CREATE TABLE IF NOT EXISTS bot_recovery_notices (
                        recovery_at TEXT NOT NULL,
                        telegram_id INTEGER NOT NULL,
                        sent_at TEXT NOT NULL,
                        PRIMARY KEY (recovery_at, telegram_id)
                    );

                    CREATE TABLE IF NOT EXISTS assessment_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL,
                        username TEXT,
                        score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 10),
                        percentage INTEGER NOT NULL CHECK (percentage BETWEEN 0 AND 100),
                        completed_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS assessment_results_member_date
                    ON assessment_results (telegram_id, completed_at DESC);

                    CREATE TABLE IF NOT EXISTS assessments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 10),
                        total INTEGER NOT NULL CHECK (total > 0),
                        percentage INTEGER NOT NULL CHECK (percentage BETWEEN 0 AND 100),
                        strong_areas TEXT NOT NULL DEFAULT '[]',
                        weak_areas TEXT NOT NULL DEFAULT '[]',
                        completed_at TEXT NOT NULL,
                        legacy_result_id INTEGER UNIQUE
                    );

                    CREATE INDEX IF NOT EXISTS assessments_member_date
                    ON assessments (telegram_id, completed_at DESC);

                    CREATE TABLE IF NOT EXISTS assessment_answers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                        question_number INTEGER NOT NULL,
                        topic TEXT NOT NULL,
                        selected_answer TEXT NOT NULL,
                        correct_answer TEXT NOT NULL,
                        is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
                        explanation TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS assessment_answers_topic
                    ON assessment_answers (topic, is_correct);

                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        asset TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        poi TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        confirmation TEXT NOT NULL,
                        liquidity_swept INTEGER NOT NULL,
                        waited_for_retest INTEGER NOT NULL,
                        stop_loss TEXT NOT NULL,
                        take_profit TEXT NOT NULL,
                        partial_profit INTEGER NOT NULL,
                        moved_sl_to_be INTEGER NOT NULL,
                        result TEXT NOT NULL,
                        followed_plan INTEGER NOT NULL,
                        mistake TEXT NOT NULL,
                        lesson TEXT NOT NULL,
                        review_summary TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS trades_member_date
                    ON trades (telegram_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS weekly_checkins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        trades_taken INTEGER NOT NULL,
                        winners INTEGER NOT NULL,
                        losses INTEGER NOT NULL,
                        followed_plan INTEGER NOT NULL,
                        entered_without_confirmation INTEGER NOT NULL,
                        chased_missed_trade INTEGER NOT NULL,
                        moved_sl_unnecessarily INTEGER NOT NULL,
                        secured_partials INTEGER NOT NULL,
                        biggest_mistake TEXT NOT NULL,
                        next_focus TEXT NOT NULL,
                        discipline_summary TEXT NOT NULL,
                        completed_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS weekly_checkins_member_date
                    ON weekly_checkins (telegram_id, completed_at DESC);

                    CREATE TABLE IF NOT EXISTS sunday_preparations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        weekly_goal TEXT NOT NULL,
                        concept_focus TEXT NOT NULL,
                        mistake_to_avoid TEXT NOT NULL,
                        missed_setup_plan TEXT NOT NULL,
                        completed_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS progress (
                        telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id),
                        tests_completed INTEGER NOT NULL DEFAULT 0,
                        assessment_average REAL,
                        latest_assessment_score INTEGER,
                        trades_journaled INTEGER NOT NULL DEFAULT 0,
                        winning_trades INTEGER NOT NULL DEFAULT 0,
                        losing_trades INTEGER NOT NULL DEFAULT 0,
                        most_common_mistake TEXT,
                        strongest_topic TEXT,
                        weakest_topic TEXT,
                        weekly_checkins_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        reminder_type TEXT NOT NULL,
                        schedule_key TEXT NOT NULL,
                        sent_at TEXT NOT NULL,
                        UNIQUE (telegram_id, reminder_type, schedule_key)
                    );

                    CREATE TABLE IF NOT EXISTS personal_reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        reminder_text TEXT NOT NULL,
                        due_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'sent', 'cancelled')),
                        sent_at TEXT
                    );

                    CREATE INDEX IF NOT EXISTS personal_reminders_due
                    ON personal_reminders (status, due_at);

                    CREATE TABLE IF NOT EXISTS channel_posting_settings (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
                        next_category_index INTEGER NOT NULL DEFAULT 0,
                        next_promo_feature_index INTEGER NOT NULL DEFAULT 0,
                        promo_interval_days INTEGER NOT NULL DEFAULT 14,
                        last_promo_date TEXT,
                        updated_at TEXT NOT NULL
                    );

                    INSERT OR IGNORE INTO channel_posting_settings (id, updated_at)
                    VALUES (1, CURRENT_TIMESTAMP);

                    CREATE TABLE IF NOT EXISTS scheduled_channel_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        schedule_date TEXT NOT NULL UNIQUE,
                        schedule_time TEXT NOT NULL,
                        requested_category TEXT NOT NULL,
                        category TEXT NOT NULL,
                        content TEXT NOT NULL,
                        destination_chat_id INTEGER NOT NULL,
                        is_promo INTEGER NOT NULL DEFAULT 0 CHECK (is_promo IN (0, 1)),
                        bot_username TEXT,
                        status TEXT NOT NULL DEFAULT 'draft'
                            CHECK (status IN (
                                'draft', 'awaiting_edit', 'rejected', 'skipped',
                                'publishing', 'published', 'delivery_unknown',
                                'retry_wait', 'failed'
                            )),
                        preview_sent_at TEXT,
                        preview_last_attempt_at TEXT,
                        edit_admin_id INTEGER,
                        edit_mode TEXT NOT NULL DEFAULT 'replace'
                            CHECK (edit_mode IN ('replace', 'feedback')),
                        publishing_started_at TEXT,
                        retry_after_at TEXT,
                        publish_attempts INTEGER NOT NULL DEFAULT 0,
                        telegram_message_id INTEGER,
                        published_at TEXT,
                        failure_category TEXT,
                        generation_source TEXT NOT NULL DEFAULT 'local'
                            CHECK (generation_source IN ('local', 'gemini_pending', 'gemini')),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS scheduled_channel_posts_due
                    ON scheduled_channel_posts (status, schedule_date);

                    CREATE TABLE IF NOT EXISTS channel_post_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        post_id INTEGER REFERENCES scheduled_channel_posts(id),
                        action TEXT NOT NULL,
                        admin_id INTEGER,
                        details TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS channel_history_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        posted_at TEXT NOT NULL,
                        archived_at TEXT NOT NULL,
                        UNIQUE (chat_id, message_id)
                    );

                    CREATE INDEX IF NOT EXISTS channel_history_posts_recent
                    ON channel_history_posts (chat_id, posted_at DESC);

                    CREATE TABLE IF NOT EXISTS dm_coaching_interactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        username TEXT,
                        question TEXT NOT NULL,
                        coach_response TEXT NOT NULL,
                        detected_topic TEXT NOT NULL,
                        mistakes_identified TEXT NOT NULL DEFAULT '',
                        lesson_learned TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS dm_coaching_member_date
                    ON dm_coaching_interactions (telegram_id, created_at DESC);

                    CREATE INDEX IF NOT EXISTS dm_coaching_topic_date
                    ON dm_coaching_interactions (detected_topic, created_at DESC);

                    CREATE TABLE IF NOT EXISTS dm_coach_mistakes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        interaction_id INTEGER NOT NULL REFERENCES dm_coaching_interactions(id)
                            ON DELETE CASCADE,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                        mistake TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS dm_coach_mistakes_mistake
                    ON dm_coach_mistakes (mistake);

                    CREATE TABLE IF NOT EXISTS knowledge_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        topic TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'awaiting_research'
                            CHECK (status IN (
                                'covered', 'awaiting_research', 'awaiting_approval',
                                'approved', 'rejected', 'retired'
                            )),
                        confidence TEXT NOT NULL DEFAULT 'low'
                            CHECK (confidence IN ('high', 'low')),
                        review_reason TEXT NOT NULL DEFAULT '',
                        proposed_answer TEXT,
                        approved_answer TEXT,
                        source_urls TEXT NOT NULL DEFAULT '',
                        research_notes TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        last_researched_at TEXT,
                        approved_at TEXT,
                        last_reviewed_at TEXT,
                        review_after TEXT,
                        draft_review_after TEXT
                    );

                    CREATE INDEX IF NOT EXISTS knowledge_items_status_date
                    ON knowledge_items (status, last_seen_at DESC);

                    CREATE TABLE IF NOT EXISTS knowledge_item_examples (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_id INTEGER NOT NULL REFERENCES knowledge_items(id)
                            ON DELETE CASCADE,
                        interaction_id INTEGER NOT NULL UNIQUE
                            REFERENCES dm_coaching_interactions(id) ON DELETE CASCADE,
                        question TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS knowledge_examples_item
                    ON knowledge_item_examples (item_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS knowledge_versions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_id INTEGER NOT NULL REFERENCES knowledge_items(id)
                            ON DELETE CASCADE,
                        version INTEGER NOT NULL,
                        answer TEXT NOT NULL,
                        source_urls TEXT NOT NULL,
                        research_notes TEXT NOT NULL DEFAULT '',
                        admin_telegram_id INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        review_after TEXT,
                        UNIQUE (item_id, version)
                    );

                    CREATE INDEX IF NOT EXISTS knowledge_versions_item_date
                    ON knowledge_versions (item_id, version DESC);

                    CREATE TABLE IF NOT EXISTS knowledge_feedback (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        interaction_id INTEGER NOT NULL UNIQUE
                            REFERENCES dm_coaching_interactions(id) ON DELETE CASCADE,
                        item_id INTEGER NOT NULL REFERENCES knowledge_items(id)
                            ON DELETE CASCADE,
                        reaction TEXT NOT NULL
                            CHECK (reaction IN ('helpful', 'unhelpful', 'unclear')),
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS knowledge_feedback_item
                    ON knowledge_feedback (item_id, reaction);

                    CREATE TABLE IF NOT EXISTS coach_challenge_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL REFERENCES users(telegram_id)
                            ON DELETE CASCADE,
                        challenge_id TEXT NOT NULL,
                        challenge_kind TEXT NOT NULL
                            CHECK (challenge_kind IN ('challenge', 'daily')),
                        presented_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS coach_challenge_history_recent
                    ON coach_challenge_history (telegram_id, presented_at DESC, id DESC);

                    CREATE TABLE IF NOT EXISTS coach_learning_rewards (
                        telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id)
                            ON DELETE CASCADE,
                        learning_points INTEGER NOT NULL DEFAULT 0
                            CHECK (learning_points >= 0),
                        questions_practiced INTEGER NOT NULL DEFAULT 0
                            CHECK (questions_practiced >= 0),
                        correct_answers INTEGER NOT NULL DEFAULT 0
                            CHECK (correct_answers >= 0),
                        challenges_completed INTEGER NOT NULL DEFAULT 0
                            CHECK (challenges_completed >= 0),
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                self._ensure_user_column(
                    connection,
                    "zoom_class_reminders_enabled",
                    "INTEGER NOT NULL DEFAULT 0",
                )
                self._ensure_user_column(
                    connection,
                    "reminders_stopped",
                    "INTEGER NOT NULL DEFAULT 0",
                )
                self._ensure_table_column(
                    connection,
                    "knowledge_items",
                    "draft_review_after",
                    "TEXT",
                )
                self._ensure_table_column(
                    connection,
                    "scheduled_channel_posts",
                    "edit_mode",
                    "TEXT NOT NULL DEFAULT 'replace'",
                )
                self._ensure_table_column(
                    connection,
                    "scheduled_channel_posts",
                    "generation_source",
                    "TEXT NOT NULL DEFAULT 'local'",
                )
                self._migrate_legacy_assessments(connection)
                member_ids = connection.execute(
                    "SELECT telegram_id FROM users"
                ).fetchall()
                for member in member_ids:
                    self._refresh_progress(connection, int(member["telegram_id"]))
        finally:
            connection.close()

    @staticmethod
    def _ensure_user_column(
        connection: sqlite3.Connection, column_name: str, definition: str
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE users ADD COLUMN {column_name} {definition}"
            )

    @staticmethod
    def _ensure_table_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )

    @staticmethod
    def _migrate_legacy_assessments(connection: sqlite3.Connection) -> None:
        """Keep quiz scores from the first version when its database is upgraded."""
        legacy_rows = connection.execute(
            """
            SELECT id, telegram_id, username, score, percentage, completed_at
            FROM assessment_results
            """
        ).fetchall()
        for row in legacy_rows:
            completed_at = str(row["completed_at"])
            connection.execute(
                """
                INSERT OR IGNORE INTO users
                    (telegram_id, username, started_at, last_interaction_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    row["telegram_id"],
                    row["username"],
                    completed_at,
                    completed_at,
                ),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO assessments
                    (telegram_id, score, total, percentage, completed_at, legacy_result_id)
                VALUES (?, ?, 10, ?, ?, ?)
                """,
                (
                    row["telegram_id"],
                    row["score"],
                    row["percentage"],
                    completed_at,
                    row["id"],
                ),
            )
            # Older records do not contain individual answers or topic breakdowns.
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE progress SET updated_at = ?
                    WHERE telegram_id = ?
                    """,
                    (completed_at, row["telegram_id"]),
                )

    def register_user(
        self,
        *,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        chat_id: int,
        is_private: bool,
        at: str | None = None,
    ) -> None:
        timestamp = at or utc_now()
        private_chat_id = chat_id if is_private else None
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO users
                        (telegram_id, username, first_name, chat_id, is_private,
                         started_at, last_interaction_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        username = COALESCE(excluded.username, users.username),
                        first_name = COALESCE(excluded.first_name, users.first_name),
                        chat_id = COALESCE(excluded.chat_id, users.chat_id),
                        is_private = CASE
                            WHEN excluded.is_private = 1 THEN 1 ELSE users.is_private
                        END,
                        last_interaction_at = excluded.last_interaction_at
                    """,
                    (
                        telegram_id,
                        username,
                        first_name,
                        private_chat_id,
                        int(is_private),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO progress (telegram_id, updated_at) VALUES (?, ?)",
                    (telegram_id, timestamp),
                )
        finally:
            connection.close()

    def record_successful_bot_poll(
        self,
        *,
        at: str | None = None,
        started_at: str | None = None,
        recovery_threshold_seconds: int = 30 * 60,
    ) -> float | None:
        """Persist polling health and record a recovery after a long outage."""
        timestamp = at or utc_now()
        poll_started_at = started_at or timestamp
        connection = self._connect()
        try:
            with connection:
                row = connection.execute(
                    """
                    SELECT last_successful_poll_at
                    FROM bot_runtime_state
                    WHERE id = 1
                    """
                ).fetchone()
                gap_seconds: float | None = None
                previous = row["last_successful_poll_at"] if row else None
                if isinstance(previous, str) and previous:
                    try:
                        previous_at = datetime.fromisoformat(previous)
                        current_at = datetime.fromisoformat(poll_started_at)
                        if previous_at.tzinfo is None:
                            previous_at = previous_at.replace(tzinfo=timezone.utc)
                        if current_at.tzinfo is None:
                            current_at = current_at.replace(tzinfo=timezone.utc)
                        gap_seconds = max(
                            0.0, (current_at - previous_at).total_seconds()
                        )
                    except ValueError:
                        gap_seconds = None

                if (
                    gap_seconds is not None
                    and gap_seconds >= max(0, recovery_threshold_seconds)
                ):
                    connection.execute(
                        """
                        UPDATE bot_runtime_state
                        SET last_successful_poll_at = ?,
                            last_recovery_at = ?,
                            last_recovery_gap_seconds = ?
                        WHERE id = 1
                        """,
                        (timestamp, timestamp, int(gap_seconds)),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE bot_runtime_state
                        SET last_successful_poll_at = ?
                        WHERE id = 1
                        """,
                        (timestamp,),
                    )
                return gap_seconds
        finally:
            connection.close()

    def pending_bot_recovery_notice(
        self, telegram_id: int
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT state.last_recovery_at, state.last_recovery_gap_seconds,
                       (
                           SELECT COUNT(*)
                           FROM bot_recovery_notices AS sent
                           WHERE sent.telegram_id = ?
                       ) AS previous_notice_count
                FROM bot_runtime_state AS state
                LEFT JOIN bot_recovery_notices AS notice
                  ON notice.recovery_at = state.last_recovery_at
                 AND notice.telegram_id = ?
                WHERE state.id = 1
                  AND state.last_recovery_at IS NOT NULL
                  AND notice.telegram_id IS NULL
                """,
                (telegram_id, telegram_id),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def mark_bot_recovery_notice_sent(
        self, telegram_id: int, recovery_at: str, *, at: str | None = None
    ) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO bot_recovery_notices
                        (recovery_at, telegram_id, sent_at)
                    VALUES (?, ?, ?)
                    """,
                    (recovery_at, telegram_id, at or utc_now()),
                )
        finally:
            connection.close()

    def get_channel_posting_settings(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM channel_posting_settings WHERE id = 1"
            ).fetchone()
            return dict(row) if row else {
                "paused": 0,
                "next_category_index": 0,
                "next_promo_feature_index": 0,
                "promo_interval_days": 14,
                "last_promo_date": None,
            }
        finally:
            connection.close()

    def create_scheduled_channel_post(
        self,
        *,
        schedule_date: str,
        schedule_time: str,
        requested_category: str,
        category: str,
        content: str,
        destination_chat_id: int,
        is_promo: bool,
        bot_username: str | None,
        next_category_index: int,
        next_promo_feature_index: int,
        last_promo_date: str | None,
        status: str = "draft",
        failure_category: str | None = None,
        generation_source: str = "local",
        at: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if status not in {"draft", "failed"}:
            raise ValueError("Invalid initial channel post status.")
        if generation_source not in {"local", "gemini_pending", "gemini"}:
            raise ValueError("Invalid channel content source.")
        created_at = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                existing = connection.execute(
                    "SELECT * FROM scheduled_channel_posts WHERE schedule_date = ?",
                    (schedule_date,),
                ).fetchone()
                if existing:
                    return dict(existing), False
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO scheduled_channel_posts (
                        schedule_date, schedule_time, requested_category, category,
                        content, destination_chat_id, is_promo, bot_username, status,
                        failure_category, generation_source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        schedule_date,
                        schedule_time,
                        requested_category,
                        category,
                        content,
                        destination_chat_id,
                        int(is_promo),
                        bot_username,
                        status,
                        failure_category,
                        generation_source,
                        created_at,
                        created_at,
                    ),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        UPDATE channel_posting_settings
                        SET next_category_index = ?,
                            next_promo_feature_index = ?,
                            last_promo_date = ?,
                            updated_at = ?
                        WHERE id = 1
                        """,
                        (
                            next_category_index,
                            next_promo_feature_index,
                            last_promo_date,
                            created_at,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, details, created_at)
                        VALUES (?, 'created', ?, ?)
                        """,
                        (
                            cursor.lastrowid,
                            f"category={category}; promo={int(is_promo)}",
                            created_at,
                        ),
                    )
                row = connection.execute(
                    "SELECT * FROM scheduled_channel_posts WHERE schedule_date = ?",
                    (schedule_date,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Scheduled channel post was not saved.")
                return dict(row), bool(cursor.rowcount)
        finally:
            connection.close()

    def complete_channel_post_generation(
        self,
        post_id: int,
        *,
        category: str,
        content: str,
        bot_username: str | None,
        next_category_index: int,
        next_promo_feature_index: int,
        last_promo_date: str | None,
        action: str = "gemini_generated",
        admin_id: int | None = None,
        at: str | None = None,
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET category = ?, content = ?, bot_username = ?, status = 'draft',
                        failure_category = NULL, preview_sent_at = NULL,
                        preview_last_attempt_at = NULL, edit_admin_id = NULL,
                        edit_mode = 'replace', generation_source = 'gemini',
                        updated_at = ?
                    WHERE id = ? AND status IN ('failed', 'awaiting_edit')
                    """,
                    (category, content, bot_username, timestamp, post_id),
                )
                if cursor.rowcount:
                    settings = connection.execute(
                        """
                        SELECT next_category_index, next_promo_feature_index,
                            last_promo_date
                        FROM channel_posting_settings WHERE id = 1
                        """
                    ).fetchone()
                    current_category_index = int(
                        settings["next_category_index"] if settings else 0
                    )
                    current_feature_index = int(
                        settings["next_promo_feature_index"] if settings else 0
                    )
                    current_promo_date = (
                        str(settings["last_promo_date"])
                        if settings and settings["last_promo_date"]
                        else None
                    )
                    latest_promo_date = max(
                        (
                            value
                            for value in (current_promo_date, last_promo_date)
                            if value
                        ),
                        default=None,
                    )
                    connection.execute(
                        """
                        UPDATE channel_posting_settings
                        SET next_category_index = ?, next_promo_feature_index = ?,
                            last_promo_date = ?, updated_at = ?
                        WHERE id = 1
                        """,
                        (
                            max(current_category_index, next_category_index),
                            max(current_feature_index, next_promo_feature_index),
                            latest_promo_date,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, admin_id, details, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (post_id, action, admin_id, category, timestamp),
                    )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def get_scheduled_channel_post(
        self, schedule_date: str
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM scheduled_channel_posts WHERE schedule_date = ?",
                (schedule_date,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def get_channel_post(self, post_id: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM scheduled_channel_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def update_channel_post_bot_username(
        self, post_id: int, username: str, *, at: str | None = None
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET bot_username = ?, updated_at = ?
                    WHERE id = ? AND is_promo = 1
                      AND status IN ('failed', 'awaiting_edit')
                    """,
                    (username, timestamp, post_id),
                )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def list_channel_posts(
        self, *, limit: int = 10, pending_only: bool = False
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            if pending_only:
                rows = connection.execute(
                    """
                    SELECT * FROM scheduled_channel_posts
                    WHERE status IN ('draft', 'awaiting_edit', 'failed', 'retry_wait')
                    ORDER BY schedule_date ASC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM scheduled_channel_posts
                    ORDER BY schedule_date DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def get_recent_channel_post_contents(
        self, *, limit: int = 30, chat_id: int | None = None
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            scheduled_sql = """
                SELECT id, category, content, is_promo, schedule_date, status,
                    'scheduled' AS source
                FROM scheduled_channel_posts
                WHERE content != ''
            """
            scheduled_params: list[Any] = []
            if chat_id is not None:
                scheduled_sql += " AND destination_chat_id = ?"
                scheduled_params.append(chat_id)
            scheduled_sql += " ORDER BY schedule_date DESC LIMIT ?"
            scheduled_params.append(limit)
            scheduled_rows = connection.execute(
                scheduled_sql, scheduled_params
            ).fetchall()

            history_sql = """
                SELECT message_id AS id, 'channel_history' AS category, content,
                    0 AS is_promo, posted_at AS schedule_date, 'observed' AS status,
                    'channel' AS source
                FROM channel_history_posts
            """
            history_params: list[Any] = []
            if chat_id is not None:
                history_sql += " WHERE chat_id = ?"
                history_params.append(chat_id)
            history_sql += " ORDER BY posted_at DESC LIMIT ?"
            history_params.append(limit)
            history_rows = connection.execute(history_sql, history_params).fetchall()
            combined = [dict(row) for row in scheduled_rows]
            combined.extend(dict(row) for row in history_rows)
            combined.sort(
                key=lambda item: str(item.get("schedule_date") or ""), reverse=True
            )
            unique: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in combined:
                content = str(item.get("content") or "").strip()
                canonical = re.sub(r"[^a-z0-9]+", "", content.casefold())
                if not canonical or canonical in seen:
                    continue
                seen.add(canonical)
                unique.append(item)
                if len(unique) >= limit:
                    break
            return unique
        finally:
            connection.close()

    def record_channel_history_post(
        self,
        chat_id: int,
        message_id: int,
        content: str,
        posted_at: str,
        *,
        at: str | None = None,
    ) -> bool:
        text = content.strip()
        if not text:
            return False
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO channel_history_posts
                        (chat_id, message_id, content, posted_at, archived_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id, message_id) DO UPDATE SET
                        content = excluded.content,
                        posted_at = excluded.posted_at,
                        archived_at = excluded.archived_at
                    """,
                    (chat_id, message_id, text[:4000], posted_at, at or utc_now()),
                )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def get_recent_channel_post_feedback(
        self, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT p.schedule_date, p.category, a.details
                FROM channel_post_actions AS a
                JOIN scheduled_channel_posts AS p ON p.id = a.post_id
                WHERE a.action = 'revision_feedback'
                ORDER BY a.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def get_latest_channel_post_feedback(self, post_id: int) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT details FROM channel_post_actions
                WHERE post_id = ? AND action = 'revision_feedback'
                ORDER BY id DESC LIMIT 1
                """,
                (post_id,),
            ).fetchone()
            return str(row["details"]) if row and row["details"] else None
        finally:
            connection.close()

    def record_channel_post_action(
        self,
        post_id: int | None,
        action: str,
        *,
        admin_id: int | None = None,
        details: str | None = None,
        at: str | None = None,
    ) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO channel_post_actions
                        (post_id, action, admin_id, details, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (post_id, action, admin_id, details, at or utc_now()),
                )
        finally:
            connection.close()

    def set_channel_posting_paused(
        self, paused: bool, *, admin_id: int, at: str | None = None
    ) -> None:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE channel_posting_settings
                    SET paused = ?, updated_at = ? WHERE id = 1
                    """,
                    (int(paused), timestamp),
                )
                connection.execute(
                    """
                    INSERT INTO channel_post_actions
                        (post_id, action, admin_id, details, created_at)
                    VALUES (NULL, ?, ?, ?, ?)
                    """,
                    (
                        "paused" if paused else "resumed",
                        admin_id,
                        "Scheduled channel publishing",
                        timestamp,
                    ),
                )
        finally:
            connection.close()

    def set_channel_promo_interval(
        self, interval_days: int, *, admin_id: int, at: str | None = None
    ) -> None:
        if interval_days not in {7, 14, 28}:
            raise ValueError("Unsupported bot-promotion interval.")
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE channel_posting_settings
                    SET promo_interval_days = ?, updated_at = ?
                    WHERE id = 1
                    """,
                    (interval_days, timestamp),
                )
                connection.execute(
                    """
                    INSERT INTO channel_post_actions
                        (post_id, action, admin_id, details, created_at)
                    VALUES (NULL, 'promo_interval_changed', ?, ?, ?)
                    """,
                    (admin_id, f"interval_days={interval_days}", timestamp),
                )
        finally:
            connection.close()

    def mark_channel_post_preview_attempted(
        self, post_id: int, *, at: str | None = None
    ) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET preview_last_attempt_at = ?, updated_at = ?
                    WHERE id = ? AND preview_sent_at IS NULL
                    """,
                    (at or utc_now(), at or utc_now(), post_id),
                )
        finally:
            connection.close()

    def mark_channel_post_preview_sent(
        self, post_id: int, *, at: str | None = None
    ) -> None:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET preview_sent_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, post_id),
                )
                connection.execute(
                    """
                    INSERT INTO channel_post_actions
                        (post_id, action, created_at)
                    VALUES (?, 'preview_sent', ?)
                    """,
                    (post_id, timestamp),
                )
        finally:
            connection.close()

    def start_channel_post_edit(
        self, post_id: int, *, admin_id: int, at: str | None = None
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = 'awaiting_edit', edit_admin_id = ?,
                        edit_mode = 'replace', updated_at = ?
                    WHERE id = ? AND status = 'draft'
                    """,
                    (admin_id, timestamp, post_id),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, admin_id, created_at)
                        VALUES (?, 'edit_started', ?, ?)
                        """,
                        (post_id, admin_id, timestamp),
                    )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def start_channel_post_revision(
        self, post_id: int, *, admin_id: int, at: str | None = None
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = 'awaiting_edit', edit_admin_id = ?,
                        edit_mode = 'feedback', updated_at = ?
                    WHERE id = ? AND status = 'draft'
                    """,
                    (admin_id, timestamp, post_id),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, admin_id, created_at)
                        VALUES (?, 'revision_started', ?, ?)
                        """,
                        (post_id, admin_id, timestamp),
                    )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def pending_channel_post_edit(
        self, admin_id: int
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM scheduled_channel_posts
                WHERE status = 'awaiting_edit' AND edit_admin_id = ?
                ORDER BY schedule_date ASC LIMIT 1
                """,
                (admin_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def save_channel_post_edit(
        self, post_id: int, content: str, *, admin_id: int, at: str | None = None
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET content = ?, status = 'draft', edit_admin_id = NULL,
                        edit_mode = 'replace',
                        preview_sent_at = NULL, preview_last_attempt_at = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'awaiting_edit' AND edit_admin_id = ?
                    """,
                    (content, timestamp, post_id, admin_id),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, admin_id, details, created_at)
                        VALUES (?, 'edited', ?, ?, ?)
                        """,
                        (post_id, admin_id, content, timestamp),
                    )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def cancel_channel_post_edit(
        self, admin_id: int, *, at: str | None = None
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                rows = connection.execute(
                    """
                    SELECT id FROM scheduled_channel_posts
                    WHERE status = 'awaiting_edit' AND edit_admin_id = ?
                    """,
                    (admin_id,),
                ).fetchall()
                if not rows:
                    return False
                connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = 'draft', edit_admin_id = NULL,
                        edit_mode = 'replace', updated_at = ?
                    WHERE status = 'awaiting_edit' AND edit_admin_id = ?
                    """,
                    (timestamp, admin_id),
                )
                connection.executemany(
                    """
                    INSERT INTO channel_post_actions
                        (post_id, action, admin_id, created_at)
                    VALUES (?, 'edit_cancelled', ?, ?)
                    """,
                    [(row["id"], admin_id, timestamp) for row in rows],
                )
                return True
        finally:
            connection.close()

    def reserve_channel_post_publish(
        self, post_id: int, *, at: str | None = None
    ) -> int | None:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = 'publishing', publishing_started_at = ?,
                        retry_after_at = NULL, failure_category = NULL,
                        publish_attempts = publish_attempts + 1, updated_at = ?
                    WHERE id = ? AND status IN ('draft', 'failed', 'retry_wait')
                    """,
                    (timestamp, timestamp, post_id),
                )
                if cursor.rowcount:
                    row = connection.execute(
                        "SELECT publish_attempts FROM scheduled_channel_posts WHERE id = ?",
                        (post_id,),
                    ).fetchone()
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, created_at)
                        VALUES (?, 'publishing_started', ?)
                        """,
                        (post_id, timestamp),
                    )
                    return int(row["publish_attempts"])
                return None
        finally:
            connection.close()

    def complete_channel_post_publish(
        self,
        post_id: int,
        *,
        telegram_message_id: int | None,
        at: str | None = None,
        admin_id: int | None = None,
    ) -> None:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = 'published', telegram_message_id = ?,
                        published_at = ?, failure_category = NULL, updated_at = ?
                    WHERE id = ? AND status = 'publishing'
                    """,
                    (telegram_message_id, timestamp, timestamp, post_id),
                )
                connection.execute(
                    """
                    INSERT INTO channel_post_actions
                        (post_id, action, admin_id, details, created_at)
                    VALUES (?, 'published', ?, ?, ?)
                    """,
                    (
                        post_id,
                        admin_id,
                        f"telegram_message_id={telegram_message_id}",
                        timestamp,
                    ),
                )
        finally:
            connection.close()

    def fail_channel_post_publish(
        self,
        post_id: int,
        *,
        status: str,
        failure_category: str,
        retry_after_at: str | None = None,
        at: str | None = None,
    ) -> None:
        if status not in {"failed", "delivery_unknown", "retry_wait"}:
            raise ValueError("Invalid channel post failure status.")
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = ?, failure_category = ?, retry_after_at = ?,
                        updated_at = ?
                    WHERE id = ? AND status = 'publishing'
                    """,
                    (status, failure_category, retry_after_at, timestamp, post_id),
                )
                connection.execute(
                    """
                    INSERT INTO channel_post_actions
                        (post_id, action, details, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        post_id,
                        status,
                        failure_category,
                        timestamp,
                    ),
                )
        finally:
            connection.close()

    def recover_inflight_channel_posts(
        self, *, at: str | None = None
    ) -> list[dict[str, Any]]:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                rows = connection.execute(
                    """
                    SELECT * FROM scheduled_channel_posts WHERE status = 'publishing'
                    """
                ).fetchall()
                if rows:
                    connection.execute(
                        """
                        UPDATE scheduled_channel_posts
                        SET status = 'delivery_unknown',
                            failure_category = 'restart_during_send',
                            updated_at = ?
                        WHERE status = 'publishing'
                        """,
                        (timestamp,),
                    )
                    connection.executemany(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, details, created_at)
                        VALUES (?, 'delivery_unknown', 'restart_during_send', ?)
                        """,
                        [(row["id"], timestamp) for row in rows],
                    )
                return [dict(row) for row in rows]
        finally:
            connection.close()

    def set_channel_post_status(
        self,
        post_id: int,
        status: str,
        *,
        action: str,
        admin_id: int | None = None,
        details: str | None = None,
        failure_category: str | None = None,
        at: str | None = None,
    ) -> bool:
        allowed_statuses = {"draft", "failed", "rejected", "skipped"}
        if status not in allowed_statuses:
            raise ValueError("Invalid channel post status transition.")
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = ?, edit_admin_id = NULL,
                        failure_category = ?,
                        updated_at = ?
                    WHERE id = ? AND status IN (
                        'draft', 'awaiting_edit', 'failed', 'retry_wait'
                    )
                    """,
                    (
                        status,
                        failure_category if status == "failed" else None,
                        timestamp,
                        post_id,
                    ),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, admin_id, details, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (post_id, action, admin_id, details, timestamp),
                    )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def confirm_unknown_channel_post(
        self, post_id: int, *, admin_id: int, at: str | None = None
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = 'published', published_at = ?, failure_category = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = 'delivery_unknown'
                    """,
                    (timestamp, timestamp, post_id),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, admin_id, details, created_at)
                        VALUES (?, 'admin_confirmed_published', ?, ?, ?)
                        """,
                        (post_id, admin_id, "No message ID was available.", timestamp),
                    )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def resolve_unknown_channel_post_for_retry(
        self, post_id: int, *, admin_id: int, at: str | None = None
    ) -> bool:
        timestamp = at or utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_channel_posts
                    SET status = 'failed', failure_category = 'admin_checked_not_posted',
                        updated_at = ?
                    WHERE id = ? AND status = 'delivery_unknown'
                    """,
                    (timestamp, post_id),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        INSERT INTO channel_post_actions
                            (post_id, action, admin_id, details, created_at)
                        VALUES (?, 'admin_checked_not_posted', ?, ?, ?)
                        """,
                        (post_id, admin_id, "Admin explicitly authorized a retry.", timestamp),
                    )
                return bool(cursor.rowcount)
        finally:
            connection.close()

    def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def reminders_enabled(self, telegram_id: int) -> bool:
        user = self.get_user(telegram_id)
        return bool(user and user["reminders_enabled"])

    def set_reminders_enabled(self, telegram_id: int, enabled: bool) -> bool:
        connection = self._connect()
        try:
            with connection:
                user = connection.execute(
                    "SELECT is_private, chat_id FROM users WHERE telegram_id = ?",
                    (telegram_id,),
                ).fetchone()
                if not user:
                    return False
                if enabled and (not user["is_private"] or not user["chat_id"]):
                    return False
                connection.execute(
                    """
                    UPDATE users SET reminders_enabled = ?, last_interaction_at = ?
                    WHERE telegram_id = ?
                    """,
                    (int(enabled), utc_now(), telegram_id),
                )
            return True
        finally:
            connection.close()

    def class_reminders_enabled(self, telegram_id: int) -> bool:
        user = self.get_user(telegram_id)
        return bool(user and user["zoom_class_reminders_enabled"])

    def set_class_reminders_enabled(self, telegram_id: int, enabled: bool) -> bool:
        connection = self._connect()
        try:
            with connection:
                user = connection.execute(
                    "SELECT is_private, chat_id FROM users WHERE telegram_id = ?",
                    (telegram_id,),
                ).fetchone()
                if not user:
                    return False
                if enabled and (not user["is_private"] or not user["chat_id"]):
                    return False
                connection.execute(
                    """
                    UPDATE users SET zoom_class_reminders_enabled = ?,
                        last_interaction_at = ?
                    WHERE telegram_id = ?
                    """,
                    (int(enabled), utc_now(), telegram_id),
                )
            return True
        finally:
            connection.close()

    def reminders_stopped(self, telegram_id: int) -> bool:
        user = self.get_user(telegram_id)
        return bool(user and user["reminders_stopped"])

    def set_reminders_stopped(self, telegram_id: int, stopped: bool) -> bool:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE users
                    SET reminders_stopped = ?,
                        reminders_enabled = CASE WHEN ? = 1 THEN 0 ELSE reminders_enabled END,
                        zoom_class_reminders_enabled = CASE
                            WHEN ? = 1 THEN 0 ELSE zoom_class_reminders_enabled
                        END,
                        last_interaction_at = ?
                    WHERE telegram_id = ?
                    """,
                    (
                        int(stopped),
                        int(stopped),
                        int(stopped),
                        utc_now(),
                        telegram_id,
                    ),
                )
                if stopped:
                    connection.execute(
                        """
                        UPDATE personal_reminders
                        SET status = 'cancelled'
                        WHERE telegram_id = ? AND status = 'pending'
                        """,
                        (telegram_id,),
                    )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def create_personal_reminder(
        self,
        telegram_id: int,
        reminder_text: str,
        due_at: datetime,
        *,
        created_at: str | None = None,
    ) -> int | None:
        """Create a private one-time reminder for an active member."""
        connection = self._connect()
        try:
            with connection:
                user = connection.execute(
                    """
                    SELECT is_private, chat_id, reminders_stopped
                    FROM users WHERE telegram_id = ?
                    """,
                    (telegram_id,),
                ).fetchone()
                if (
                    not user
                    or not user["is_private"]
                    or not user["chat_id"]
                    or user["reminders_stopped"]
                ):
                    return None
                cursor = connection.execute(
                    """
                    INSERT INTO personal_reminders
                        (telegram_id, reminder_text, due_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        telegram_id,
                        reminder_text,
                        due_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        created_at or utc_now(),
                    ),
                )
                return int(cursor.lastrowid)
        finally:
            connection.close()

    def due_personal_reminders(self, now: datetime) -> list[dict[str, Any]]:
        due_at = now.astimezone(timezone.utc).isoformat(timespec="seconds")
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT r.id, r.telegram_id, r.reminder_text, r.due_at, u.chat_id
                FROM personal_reminders AS r
                JOIN users AS u ON u.telegram_id = r.telegram_id
                WHERE r.status = 'pending' AND r.due_at <= ?
                  AND u.is_private = 1 AND u.chat_id IS NOT NULL
                ORDER BY r.due_at, r.id
                """,
                (due_at,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def mark_personal_reminder_sent(
        self, reminder_id: int, *, sent_at: str | None = None
    ) -> bool:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE personal_reminders
                    SET status = 'sent', sent_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (sent_at or utc_now(), reminder_id),
                )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def pending_personal_reminders(
        self, telegram_id: int, limit: int = 5
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT reminder_text, due_at
                FROM personal_reminders
                WHERE telegram_id = ? AND status = 'pending'
                ORDER BY due_at, id LIMIT ?
                """,
                (telegram_id, max(1, min(limit, 20))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def reminder_recipients(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT telegram_id, chat_id, first_name
                FROM users
                WHERE started_at IS NOT NULL
                  AND is_private = 1
                  AND chat_id IS NOT NULL
                  AND reminders_enabled = 1
                  AND reminders_stopped = 0
                ORDER BY telegram_id
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def class_reminder_recipients(self) -> list[dict[str, Any]]:
        return self.active_private_dm_recipients()

    def active_private_dm_recipients(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT telegram_id, chat_id, first_name
                FROM users
                WHERE started_at IS NOT NULL
                  AND is_private = 1
                  AND chat_id IS NOT NULL
                  AND reminders_stopped = 0
                ORDER BY telegram_id
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def reminder_was_sent(
        self, telegram_id: int, reminder_type: str, schedule_key: str
    ) -> bool:
        connection = self._connect()
        try:
            return (
                connection.execute(
                    """
                    SELECT 1 FROM reminders
                    WHERE telegram_id = ? AND reminder_type = ? AND schedule_key = ?
                    """,
                    (telegram_id, reminder_type, schedule_key),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()

    def record_reminder_sent(
        self, telegram_id: int, reminder_type: str, schedule_key: str
    ) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO reminders
                        (telegram_id, reminder_type, schedule_key, sent_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (telegram_id, reminder_type, schedule_key, utc_now()),
                )
        finally:
            connection.close()

    def save_assessment(
        self, telegram_id: int, username: str | None, result: AssessmentResult
    ) -> int:
        completed_at = utc_now()
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO users
                        (telegram_id, username, started_at, last_interaction_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        username = COALESCE(excluded.username, users.username),
                        last_interaction_at = excluded.last_interaction_at
                    """,
                    (telegram_id, username, completed_at, completed_at),
                )
                cursor = connection.execute(
                    """
                    INSERT INTO assessments
                        (telegram_id, score, total, percentage,
                         strong_areas, weak_areas, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        telegram_id,
                        result.score,
                        result.total,
                        result.percentage,
                        "\n".join(result.strong_areas),
                        "\n".join(result.weak_areas),
                        completed_at,
                    ),
                )
                assessment_id = int(cursor.lastrowid)
                connection.executemany(
                    """
                    INSERT INTO assessment_answers
                        (assessment_id, question_number, topic, selected_answer,
                         correct_answer, is_correct, explanation)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            assessment_id,
                            answer.question_number,
                            answer.topic,
                            answer.selected_answer,
                            answer.correct_answer,
                            int(answer.is_correct),
                            answer.explanation,
                        )
                        for answer in result.answers
                    ],
                )
                self._refresh_progress(connection, telegram_id)
            return assessment_id
        finally:
            connection.close()

    def save_trade(
        self, telegram_id: int, data: dict[str, Any], review_summary: str
    ) -> int:
        created_at = utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO trades (
                        telegram_id, asset, direction, poi, timeframe, confirmation,
                        liquidity_swept, waited_for_retest, stop_loss, take_profit,
                        partial_profit, moved_sl_to_be, result, followed_plan,
                        mistake, lesson, review_summary, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        telegram_id,
                        data["asset"],
                        data["direction"],
                        data["poi"],
                        data["timeframe"],
                        data["confirmation"],
                        int(data["liquidity_swept"]),
                        int(data["waited_for_retest"]),
                        data["stop_loss"],
                        data["take_profit"],
                        int(data["partial_profit"]),
                        int(data["moved_sl_to_be"]),
                        data["result"],
                        int(data["followed_plan"]),
                        data["mistake"],
                        data["lesson"],
                        review_summary,
                        created_at,
                    ),
                )
                trade_id = int(cursor.lastrowid)
                self._refresh_progress(connection, telegram_id)
            return trade_id
        finally:
            connection.close()

    def save_weekly_checkin(
        self, telegram_id: int, data: dict[str, Any], summary: str
    ) -> int:
        completed_at = utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO weekly_checkins (
                        telegram_id, trades_taken, winners, losses, followed_plan,
                        entered_without_confirmation, chased_missed_trade,
                        moved_sl_unnecessarily, secured_partials, biggest_mistake,
                        next_focus, discipline_summary, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        telegram_id,
                        data["trades_taken"],
                        data["winners"],
                        data["losses"],
                        int(data["followed_plan"]),
                        int(data["entered_without_confirmation"]),
                        int(data["chased_missed_trade"]),
                        int(data["moved_sl_unnecessarily"]),
                        int(data["secured_partials"]),
                        data["biggest_mistake"],
                        data["next_focus"],
                        summary,
                        completed_at,
                    ),
                )
                connection.execute(
                    "UPDATE users SET last_checkin_at = ? WHERE telegram_id = ?",
                    (completed_at, telegram_id),
                )
                checkin_id = int(cursor.lastrowid)
                self._refresh_progress(connection, telegram_id)
            return checkin_id
        finally:
            connection.close()

    def save_sunday_preparation(
        self, telegram_id: int, data: dict[str, Any]
    ) -> int:
        completed_at = utc_now()
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO sunday_preparations (
                        telegram_id, weekly_goal, concept_focus, mistake_to_avoid,
                        missed_setup_plan, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        telegram_id,
                        data["weekly_goal"],
                        data["concept_focus"],
                        data["mistake_to_avoid"],
                        data["missed_setup_plan"],
                        completed_at,
                    ),
                )
                connection.execute(
                    "UPDATE users SET last_checkin_at = ? WHERE telegram_id = ?",
                    (completed_at, telegram_id),
                )
                return int(cursor.lastrowid)
        finally:
            connection.close()

    def progress_for(self, telegram_id: int) -> dict[str, Any]:
        connection = self._connect()
        try:
            self._refresh_progress(connection, telegram_id)
            connection.commit()
            row = connection.execute(
                "SELECT * FROM progress WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            return dict(row) if row else {}
        finally:
            connection.close()

    def recent_trades(self, telegram_id: int, limit: int = 5) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT id, asset, direction, result, followed_plan, mistake,
                       review_summary, created_at
                FROM trades WHERE telegram_id = ?
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (telegram_id, max(1, min(limit, 20))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def trade_by_id(self, telegram_id: int, trade_id: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM trades WHERE telegram_id = ? AND id = ?
                """,
                (telegram_id, trade_id),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def recent_checkins(
        self, telegram_id: int, limit: int = 4
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT trades_taken, winners, losses, discipline_summary,
                       next_focus, completed_at
                FROM weekly_checkins WHERE telegram_id = ?
                ORDER BY completed_at DESC, id DESC LIMIT ?
                """,
                (telegram_id, max(1, min(limit, 12))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def latest_sunday_preparation(
        self, telegram_id: int
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT weekly_goal, concept_focus, mistake_to_avoid,
                       missed_setup_plan, completed_at
                FROM sunday_preparations
                WHERE telegram_id = ?
                ORDER BY completed_at DESC, id DESC LIMIT 1
                """,
                (telegram_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def admin_stats(self, active_since: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            basic = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS members,
                    (SELECT COUNT(*) FROM users WHERE last_interaction_at >= ?) AS active_members,
                    (SELECT COUNT(*) FROM assessments) AS assessments,
                    (SELECT AVG(percentage) FROM assessments) AS average_score,
                    (SELECT COUNT(*) FROM trades) AS trades,
                    (SELECT COUNT(*) FROM trades WHERE result = 'Win') AS winning_trades,
                    (SELECT COUNT(*) FROM weekly_checkins WHERE completed_at >= ?) AS weekly_participation
                """,
                (active_since, active_since),
            ).fetchone()
            weakest = connection.execute(
                """
                SELECT topic, COUNT(*) AS misses
                FROM assessment_answers
                WHERE is_correct = 0
                GROUP BY topic
                ORDER BY misses DESC, topic ASC
                LIMIT 1
                """
            ).fetchone()
            common_mistake = connection.execute(
                """
                SELECT mistake, COUNT(*) AS occurrences
                FROM trades
                WHERE trim(mistake) <> ''
                  AND lower(trim(mistake)) NOT IN ('none', 'n/a', 'no mistake')
                GROUP BY lower(trim(mistake))
                ORDER BY occurrences DESC, lower(trim(mistake)) ASC
                LIMIT 1
                """
            ).fetchone()
            return {
                **dict(basic),
                "most_common_weak_topic": weakest["topic"] if weakest else None,
                "most_common_mistake": common_mistake["mistake"] if common_mistake else None,
            }
        finally:
            connection.close()

    def admin_dashboard_data(
        self,
        active_since: str,
        checkin_cutoff: str,
        *,
        low_score_below: int = 60,
    ) -> dict[str, Any]:
        connection = self._connect()
        try:
            counts = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS total_members,
                    (SELECT COUNT(*) FROM users WHERE last_interaction_at >= ?) AS active_this_week,
                    (
                        SELECT COUNT(DISTINCT telegram_id) FROM assessments
                    ) AS assessed_members,
                    (SELECT AVG(percentage) FROM assessments) AS average_score,
                    (SELECT COUNT(*) FROM trades) AS trades_journaled,
                    (
                        SELECT COUNT(*) FROM users u
                        WHERE (
                            SELECT latest.percentage FROM assessments latest
                            WHERE latest.telegram_id = u.telegram_id
                            ORDER BY latest.completed_at DESC, latest.id DESC
                            LIMIT 1
                        ) < ?
                    ) AS low_score_members,
                    (
                        SELECT COUNT(*) FROM users
                        WHERE last_checkin_at IS NULL OR last_checkin_at < ?
                    ) AS no_recent_checkin
                """,
                (active_since, low_score_below, checkin_cutoff),
            ).fetchone()
            top_members = connection.execute(
                """
                SELECT u.telegram_id, u.username, u.first_name,
                       COUNT(a.id) AS assessment_count,
                       ROUND(AVG(a.percentage), 1) AS average_score
                FROM assessments a
                JOIN users u ON u.telegram_id = a.telegram_id
                GROUP BY u.telegram_id
                ORDER BY average_score DESC, assessment_count DESC, u.telegram_id ASC
                LIMIT 5
                """
            ).fetchall()
            low_members = connection.execute(
                """
                SELECT u.telegram_id, u.username, u.first_name,
                       a.score, a.total, a.percentage, a.completed_at
                FROM assessments a
                JOIN users u ON u.telegram_id = a.telegram_id
                WHERE a.id = (
                    SELECT latest.id FROM assessments latest
                    WHERE latest.telegram_id = a.telegram_id
                    ORDER BY latest.completed_at DESC, latest.id DESC
                    LIMIT 1
                )
                  AND a.percentage < ?
                ORDER BY a.percentage ASC, a.completed_at DESC
                LIMIT 10
                """,
                (low_score_below,),
            ).fetchall()
            weak_topics = connection.execute(
                """
                SELECT topic, COUNT(*) AS attempts,
                       SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) AS misses,
                       ROUND(100.0 * SUM(is_correct) / COUNT(*), 1) AS accuracy
                FROM assessment_answers
                GROUP BY topic
                ORDER BY accuracy ASC, misses DESC, topic ASC
                LIMIT 12
                """
            ).fetchall()
            common_mistakes = connection.execute(
                """
                SELECT MIN(trim(mistake)) AS mistake, COUNT(*) AS occurrences
                FROM trades
                WHERE trim(mistake) <> ''
                  AND lower(trim(mistake)) NOT IN ('none', 'n/a', 'no mistake')
                GROUP BY lower(trim(mistake))
                ORDER BY occurrences DESC, lower(trim(mistake)) ASC
                LIMIT 5
                """
            ).fetchall()
            no_checkin_members = connection.execute(
                """
                SELECT telegram_id, username, first_name, last_checkin_at
                FROM users
                WHERE last_checkin_at IS NULL OR last_checkin_at < ?
                ORDER BY
                    CASE WHEN last_checkin_at IS NULL THEN 0 ELSE 1 END,
                    last_checkin_at ASC,
                    telegram_id ASC
                LIMIT 10
                """,
                (checkin_cutoff,),
            ).fetchall()
            return {
                **dict(counts),
                "top_members": [dict(row) for row in top_members],
                "low_members": [dict(row) for row in low_members],
                "weak_topics": [dict(row) for row in weak_topics],
                "common_mistakes": [dict(row) for row in common_mistakes],
                "no_checkin_members": [dict(row) for row in no_checkin_members],
                "low_score_threshold": low_score_below,
            }
        finally:
            connection.close()

    def save_dm_coaching_interaction(
        self,
        *,
        telegram_id: int,
        username: str | None,
        question: str,
        coach_response: str,
        detected_topic: str,
        mistakes_identified: list[str] | tuple[str, ...],
        lesson_learned: str,
        at: str | None = None,
    ) -> int:
        created_at = at or utc_now()
        mistakes = tuple(dict.fromkeys(
            mistake.strip() for mistake in mistakes_identified if mistake.strip()
        ))
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO dm_coaching_interactions
                        (telegram_id, username, question, coach_response,
                         detected_topic, mistakes_identified, lesson_learned, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        telegram_id,
                        username,
                        question,
                        coach_response,
                        detected_topic,
                        "\n".join(mistakes),
                        lesson_learned,
                        created_at,
                    ),
                )
                interaction_id = int(cursor.lastrowid)
                connection.executemany(
                    """
                    INSERT INTO dm_coach_mistakes
                        (interaction_id, telegram_id, mistake)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (interaction_id, telegram_id, mistake)
                        for mistake in mistakes
                    ),
                )
                connection.execute(
                    """
                    UPDATE users SET last_interaction_at = ?
                    WHERE telegram_id = ?
                    """,
                    (created_at, telegram_id),
                )
                return interaction_id
        finally:
            connection.close()

    def recent_dm_coaching_interactions(
        self, telegram_id: int, limit: int = 6
    ) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT question, coach_response, detected_topic,
                       mistakes_identified, lesson_learned, created_at
                FROM dm_coaching_interactions
                WHERE telegram_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (telegram_id, max(1, min(limit, 20))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def clear_dm_coaching_history(self, telegram_id: int) -> int:
        """Delete only this member's saved coach conversations and coach mistakes."""
        connection = self._connect()
        try:
            with connection:
                affected_items = [
                    int(row["item_id"])
                    for row in connection.execute(
                        """
                        SELECT DISTINCT e.item_id
                        FROM knowledge_item_examples e
                        JOIN dm_coaching_interactions i
                          ON i.id = e.interaction_id
                        WHERE i.telegram_id = ?
                        """,
                        (telegram_id,),
                    ).fetchall()
                ]
                cursor = connection.execute(
                    "DELETE FROM dm_coaching_interactions WHERE telegram_id = ?",
                    (telegram_id,),
                )
                for item_id in affected_items:
                    remaining = connection.execute(
                        "SELECT COUNT(*) FROM knowledge_item_examples WHERE item_id = ?",
                        (item_id,),
                    ).fetchone()[0]
                    approved = connection.execute(
                        "SELECT approved_answer FROM knowledge_items WHERE id = ?",
                        (item_id,),
                    ).fetchone()
                    if not remaining and approved and not approved["approved_answer"]:
                        connection.execute(
                            "DELETE FROM knowledge_items WHERE id = ?", (item_id,)
                        )
                return int(cursor.rowcount)
        finally:
            connection.close()

    def knowledge_items_for_matching(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            items = connection.execute(
                """
                SELECT * FROM knowledge_items
                WHERE status <> 'retired'
                ORDER BY id DESC
                LIMIT 1000
                """
            ).fetchall()
            results = []
            for item in items:
                record = dict(item)
                examples = connection.execute(
                    """
                    SELECT question FROM knowledge_item_examples
                    WHERE item_id = ? ORDER BY created_at DESC, id DESC LIMIT 20
                    """,
                    (item["id"],),
                ).fetchall()
                record["examples"] = [row["question"] for row in examples]
                results.append(record)
            return results
        finally:
            connection.close()

    def approved_knowledge_items(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self.knowledge_items_for_matching()
            if item.get("approved_answer") and item.get("status") != "retired"
        ]

    def record_knowledge_question(
        self,
        *,
        question: str,
        topic: str,
        confidence: str,
        review_reason: str,
        interaction_id: int,
        at: str | None = None,
    ) -> int:
        if confidence not in {"high", "low"}:
            raise ValueError("Knowledge confidence must be high or low.")
        created_at = at or utc_now()
        candidates = self.knowledge_items_for_matching()
        matched = find_similar_item(question, topic, candidates)
        connection = self._connect()
        try:
            with connection:
                if matched:
                    item_id = int(matched["id"])
                    connection.execute(
                        """
                        UPDATE knowledge_items
                        SET last_seen_at = ?,
                            confidence = ?,
                            review_reason = CASE
                                WHEN ? <> '' THEN ? ELSE review_reason
                            END,
                            status = CASE
                                WHEN ? = 'low'
                                  AND status IN ('covered', 'rejected')
                                    THEN 'awaiting_research'
                                WHEN ? = 'low' AND status = 'approved'
                                  AND (review_after IS NULL OR review_after < date('now'))
                                    THEN 'awaiting_research'
                                ELSE status
                            END
                        WHERE id = ?
                        """,
                        (
                            created_at,
                            confidence,
                            review_reason,
                            review_reason,
                            confidence,
                            confidence,
                            item_id,
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO knowledge_items
                            (topic, status, confidence, review_reason, created_at, last_seen_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            topic,
                            "awaiting_research" if confidence == "low" else "covered",
                            confidence,
                            review_reason,
                            created_at,
                            created_at,
                        ),
                    )
                    item_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO knowledge_item_examples
                        (item_id, interaction_id, question, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item_id, interaction_id, question, created_at),
                )
                return item_id
        finally:
            connection.close()

    def knowledge_admin_summary(self) -> dict[str, int]:
        connection = self._connect()
        try:
            statuses = {
                row["status"]: int(row["count"])
                for row in connection.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM knowledge_items GROUP BY status
                    """
                ).fetchall()
            }
            unhelpful = connection.execute(
                """
                SELECT COUNT(DISTINCT item_id)
                FROM knowledge_feedback WHERE reaction IN ('unhelpful', 'unclear')
                """
            ).fetchone()[0]
            repeated = connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT item_id FROM knowledge_item_examples
                    GROUP BY item_id HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
            return {
                **{status: statuses.get(status, 0) for status in (
                    "covered", "awaiting_research", "awaiting_approval",
                    "approved", "rejected", "retired",
                )},
                "unhelpful": int(unhelpful),
                "repeated": int(repeated),
            }
        finally:
            connection.close()

    def knowledge_queue(
        self, view: str = "awaiting_research", page: int = 0, page_size: int = 8
    ) -> tuple[int, list[dict[str, Any]]]:
        where = {
            "awaiting_research": "k.status = 'awaiting_research'",
            "awaiting_approval": "k.status = 'awaiting_approval'",
            "unhelpful": (
                "EXISTS (SELECT 1 FROM knowledge_feedback f WHERE "
                "f.item_id = k.id AND f.reaction IN ('unhelpful', 'unclear'))"
            ),
            "repeated": (
                "(SELECT COUNT(*) FROM knowledge_item_examples e "
                "WHERE e.item_id = k.id) > 1"
            ),
            "resolved": "k.status IN ('covered', 'approved', 'retired')",
            "rejected": "k.status = 'rejected'",
            "all": "k.status <> 'retired'",
        }.get(view)
        if where is None:
            raise ValueError("Unsupported knowledge queue view.")
        safe_page = max(0, page)
        safe_page_size = max(1, min(page_size, 20))
        connection = self._connect()
        try:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM knowledge_items k WHERE {where}"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT k.*,
                    (SELECT COUNT(*) FROM knowledge_item_examples e
                     WHERE e.item_id = k.id) AS occurrence_count,
                    (SELECT COUNT(*) FROM knowledge_feedback f
                     WHERE f.item_id = k.id AND f.reaction = 'helpful') AS helpful_count,
                    (SELECT COUNT(*) FROM knowledge_feedback f
                     WHERE f.item_id = k.id AND f.reaction = 'unhelpful') AS unhelpful_count,
                    (SELECT COUNT(*) FROM knowledge_feedback f
                     WHERE f.item_id = k.id AND f.reaction = 'unclear') AS unclear_count,
                    (SELECT question FROM knowledge_item_examples e
                     WHERE e.item_id = k.id ORDER BY e.created_at DESC, e.id DESC LIMIT 1)
                     AS display_question
                FROM knowledge_items k
                WHERE {where}
                ORDER BY
                    CASE k.status
                        WHEN 'awaiting_research' THEN 0
                        WHEN 'awaiting_approval' THEN 1
                        WHEN 'approved' THEN 2
                        ELSE 3
                    END,
                    occurrence_count DESC, k.last_seen_at DESC
                LIMIT ? OFFSET ?
                """,
                (safe_page_size, safe_page * safe_page_size),
            ).fetchall()
            return total, [dict(row) for row in rows]
        finally:
            connection.close()

    def knowledge_item_detail(self, item_id: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT k.*,
                    (SELECT COUNT(*) FROM knowledge_item_examples e
                     WHERE e.item_id = k.id) AS occurrence_count,
                    (SELECT COUNT(*) FROM knowledge_feedback f
                     WHERE f.item_id = k.id AND f.reaction = 'helpful') AS helpful_count,
                    (SELECT COUNT(*) FROM knowledge_feedback f
                     WHERE f.item_id = k.id AND f.reaction = 'unhelpful') AS unhelpful_count,
                    (SELECT COUNT(*) FROM knowledge_feedback f
                     WHERE f.item_id = k.id AND f.reaction = 'unclear') AS unclear_count
                FROM knowledge_items k WHERE k.id = ?
                """,
                (item_id,),
            ).fetchone()
            if not row:
                return None
            detail = dict(row)
            detail["examples"] = [
                dict(example)
                for example in connection.execute(
                    """
                    SELECT question, created_at FROM knowledge_item_examples
                    WHERE item_id = ? ORDER BY created_at DESC, id DESC LIMIT 8
                    """,
                    (item_id,),
                ).fetchall()
            ]
            detail["versions"] = [
                dict(version)
                for version in connection.execute(
                    """
                    SELECT version, answer, source_urls, research_notes,
                           admin_telegram_id, created_at, review_after
                    FROM knowledge_versions
                    WHERE item_id = ? ORDER BY version DESC LIMIT 10
                    """,
                    (item_id,),
                ).fetchall()
            ]
            return detail
        finally:
            connection.close()

    def set_knowledge_draft(self, item_id: int, answer: str) -> bool:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE knowledge_items
                    SET proposed_answer = ?, status = 'awaiting_approval', last_seen_at = ?,
                        source_urls = CASE
                            WHEN approved_answer IS NOT NULL
                              AND (approved_at IS NULL OR last_researched_at IS NULL
                                   OR last_researched_at <= approved_at)
                            THEN '' ELSE source_urls
                        END,
                        research_notes = CASE
                            WHEN approved_answer IS NOT NULL
                              AND (approved_at IS NULL OR last_researched_at IS NULL
                                   OR last_researched_at <= approved_at)
                            THEN '' ELSE research_notes
                        END,
                        last_researched_at = CASE
                            WHEN approved_answer IS NOT NULL
                              AND (approved_at IS NULL OR last_researched_at IS NULL
                                   OR last_researched_at <= approved_at)
                            THEN NULL ELSE last_researched_at
                        END,
                        draft_review_after = CASE
                            WHEN approved_answer IS NOT NULL
                              AND (approved_at IS NULL OR last_researched_at IS NULL
                                   OR last_researched_at <= approved_at)
                            THEN NULL ELSE draft_review_after
                        END
                    WHERE id = ?
                    """,
                    (answer, utc_now(), item_id),
                )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def set_knowledge_research(
        self,
        item_id: int,
        *,
        source_urls: str,
        research_notes: str,
        review_after: str,
    ) -> bool:
        connection = self._connect()
        try:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE knowledge_items
                    SET source_urls = ?, research_notes = ?, draft_review_after = ?,
                        last_researched_at = ?,
                        status = CASE
                            WHEN proposed_answer IS NOT NULL THEN 'awaiting_approval'
                            WHEN approved_answer IS NOT NULL THEN 'awaiting_research'
                            ELSE 'awaiting_research'
                        END
                    WHERE id = ?
                    """,
                    (
                        source_urls,
                        research_notes,
                        review_after or None,
                        utc_now(),
                        item_id,
                    ),
                )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def approve_knowledge_item(self, item_id: int, admin_telegram_id: int) -> int:
        connection = self._connect()
        try:
            with connection:
                item = connection.execute(
                    "SELECT * FROM knowledge_items WHERE id = ?", (item_id,)
                ).fetchone()
                if not item:
                    raise ValueError("Knowledge question not found.")
                if item["status"] != "awaiting_approval":
                    raise ValueError(
                        "Move the item to awaiting approval after adding its answer and sources."
                    )
                if not can_approve(item["proposed_answer"], item["source_urls"]):
                    raise ValueError(
                        "Add a proposed answer and at least one research source before approval."
                    )
                if (
                    item["topic"]
                    in {
                        "Broker and Platform Questions",
                        "Economic News and Fundamentals",
                        "Current Market Information",
                    }
                    or "time-sensitive" in item["review_reason"].casefold()
                ) and (
                    not item["draft_review_after"]
                ):
                    raise ValueError(
                        "Current or time-sensitive information needs a REVIEW_BY date."
                    )
                versions = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT version FROM knowledge_versions WHERE item_id = ?",
                        (item_id,),
                    ).fetchall()
                ]
                version = next_version_number(versions)
                approved_at = utc_now()
                connection.execute(
                    """
                    INSERT INTO knowledge_versions
                        (item_id, version, answer, source_urls, research_notes,
                         admin_telegram_id, created_at, review_after)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        version,
                        item["proposed_answer"],
                        item["source_urls"],
                        item["research_notes"],
                        admin_telegram_id,
                        approved_at,
                        item["draft_review_after"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE knowledge_items
                    SET approved_answer = proposed_answer,
                        proposed_answer = NULL,
                        status = 'approved',
                        confidence = 'high',
                        approved_at = ?,
                        last_reviewed_at = ?,
                        last_seen_at = ?,
                        review_after = draft_review_after,
                        draft_review_after = NULL
                    WHERE id = ?
                    """,
                    (approved_at, approved_at, approved_at, item_id),
                )
                return version
        finally:
            connection.close()

    def reject_knowledge_draft(self, item_id: int) -> bool:
        connection = self._connect()
        try:
            with connection:
                item = connection.execute(
                    "SELECT approved_answer FROM knowledge_items WHERE id = ?",
                    (item_id,),
                ).fetchone()
                if not item:
                    return False
                status = rejection_status(bool(item["approved_answer"]))
                previous = None
                if item["approved_answer"]:
                    previous = connection.execute(
                        """
                        SELECT source_urls, research_notes, review_after, created_at
                        FROM knowledge_versions
                        WHERE item_id = ? ORDER BY version DESC LIMIT 1
                        """,
                        (item_id,),
                    ).fetchone()
                cursor = connection.execute(
                    """
                    UPDATE knowledge_items
                    SET proposed_answer = NULL, status = ?, last_seen_at = ?,
                        source_urls = ?, research_notes = ?, review_after = ?,
                        last_researched_at = ?, draft_review_after = NULL
                    WHERE id = ?
                    """,
                    (
                        status,
                        utc_now(),
                        previous["source_urls"] if previous else "",
                        previous["research_notes"] if previous else "",
                        previous["review_after"] if previous else None,
                        previous["created_at"] if previous else None,
                        item_id,
                    ),
                )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def set_knowledge_status(self, item_id: int, status: str) -> bool:
        if status not in {"awaiting_research", "retired", "approved"}:
            raise ValueError("Unsupported knowledge entry status.")
        connection = self._connect()
        try:
            with connection:
                if status == "approved":
                    cursor = connection.execute(
                        """
                        UPDATE knowledge_items SET status = ?, last_seen_at = ?
                        WHERE id = ? AND approved_answer IS NOT NULL
                        """,
                        (status, utc_now(), item_id),
                    )
                else:
                    cursor = connection.execute(
                        """
                        UPDATE knowledge_items SET status = ?, last_seen_at = ?
                        WHERE id = ?
                        """,
                        (status, utc_now(), item_id),
                    )
                return cursor.rowcount > 0
        finally:
            connection.close()

    def record_knowledge_feedback(
        self, telegram_id: int, interaction_id: int, reaction: str
    ) -> bool:
        from .knowledge_feedback import REACTIONS, requires_review

        if reaction not in REACTIONS:
            raise ValueError("Unsupported Coach feedback.")
        connection = self._connect()
        try:
            with connection:
                ownership = connection.execute(
                    """
                    SELECT e.item_id
                    FROM dm_coaching_interactions i
                    JOIN knowledge_item_examples e ON e.interaction_id = i.id
                    WHERE i.id = ? AND i.telegram_id = ?
                    """,
                    (interaction_id, telegram_id),
                ).fetchone()
                if not ownership:
                    return False
                item_id = int(ownership["item_id"])
                connection.execute(
                    """
                    INSERT INTO knowledge_feedback (interaction_id, item_id, reaction, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(interaction_id) DO UPDATE SET
                        reaction = excluded.reaction,
                        created_at = excluded.created_at
                    """,
                    (interaction_id, item_id, reaction, utc_now()),
                )
                if requires_review(reaction):
                    reason = (
                        "Member reported the answer was not helpful."
                        if reaction == "unhelpful"
                        else "Member said they still do not understand the answer."
                    )
                    connection.execute(
                        """
                        UPDATE knowledge_items
                        SET status = 'awaiting_research', confidence = 'low',
                            review_reason = ?, last_seen_at = ?
                        WHERE id = ?
                        """,
                        (reason, utc_now(), item_id),
                    )
                return True
        finally:
            connection.close()

    def recent_coach_challenge_ids(
        self, telegram_id: int, limit: int = 12
    ) -> list[str]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT challenge_id FROM coach_challenge_history
                WHERE telegram_id = ?
                ORDER BY presented_at DESC, id DESC
                LIMIT ?
                """,
                (telegram_id, max(1, min(limit, 100))),
            ).fetchall()
            return [str(row["challenge_id"]) for row in rows]
        finally:
            connection.close()

    def record_coach_challenge_question(
        self,
        telegram_id: int,
        challenge_id: str,
        challenge_kind: str,
        at: str | None = None,
    ) -> None:
        if challenge_kind not in {"challenge", "daily"}:
            raise ValueError("Unsupported Coach challenge kind.")
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO coach_challenge_history
                        (telegram_id, challenge_id, challenge_kind, presented_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (telegram_id, challenge_id, challenge_kind, at or utc_now()),
                )
        finally:
            connection.close()

    def award_coach_learning_practice(
        self,
        telegram_id: int,
        questions_answered: int,
        correct_answers: int,
        *,
        completed: bool,
    ) -> dict[str, int]:
        if (
            questions_answered < 0
            or correct_answers < 0
            or correct_answers > questions_answered
        ):
            raise ValueError("Challenge answer counts must be valid non-negative totals.")
        points_awarded = questions_answered + (2 if completed else 0)
        connection = self._connect()
        try:
            with connection:
                if questions_answered:
                    connection.execute(
                        """
                        INSERT INTO coach_learning_rewards
                            (telegram_id, learning_points, questions_practiced,
                             correct_answers, challenges_completed, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(telegram_id) DO UPDATE SET
                            learning_points = learning_points + excluded.learning_points,
                            questions_practiced =
                                questions_practiced + excluded.questions_practiced,
                            correct_answers = correct_answers + excluded.correct_answers,
                            challenges_completed =
                                challenges_completed + excluded.challenges_completed,
                            updated_at = excluded.updated_at
                        """,
                        (
                            telegram_id,
                            points_awarded,
                            questions_answered,
                            correct_answers,
                            int(completed),
                            utc_now(),
                        ),
                    )
                row = connection.execute(
                    """
                    SELECT learning_points, questions_practiced, correct_answers,
                           challenges_completed
                    FROM coach_learning_rewards
                    WHERE telegram_id = ?
                    """,
                    (telegram_id,),
                ).fetchone()
                connection.commit()
                result = (
                    {
                        "learning_points": 0,
                        "questions_practiced": 0,
                        "correct_answers": 0,
                        "challenges_completed": 0,
                    }
                    if row is None
                    else {key: int(row[key]) for key in row.keys()}
                )
                result["points_awarded"] = points_awarded
                return result
        finally:
            connection.close()

    def coach_learning_progress_for(self, telegram_id: int) -> dict[str, int]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT learning_points, questions_practiced, correct_answers,
                       challenges_completed
                FROM coach_learning_rewards
                WHERE telegram_id = ?
                """,
                (telegram_id,),
            ).fetchone()
            if row is None:
                return {
                    "learning_points": 0,
                    "questions_practiced": 0,
                    "correct_answers": 0,
                    "challenges_completed": 0,
                }
            return {key: int(row[key]) for key in row.keys()}
        finally:
            connection.close()

    def admin_dm_coach_stats(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            counts = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_interactions,
                    COUNT(DISTINCT telegram_id) AS members_using_coach
                FROM dm_coaching_interactions
                """
            ).fetchone()
            common_questions = connection.execute(
                """
                SELECT MIN(question) AS question, COUNT(*) AS occurrences
                FROM dm_coaching_interactions
                WHERE trim(question) <> ''
                GROUP BY lower(trim(question))
                ORDER BY occurrences DESC, lower(trim(question)) ASC
                LIMIT 5
                """
            ).fetchall()
            weak_topics = connection.execute(
                """
                SELECT i.detected_topic AS topic,
                       COUNT(DISTINCT i.id) AS occurrences
                FROM dm_coaching_interactions i
                JOIN dm_coach_mistakes m ON m.interaction_id = i.id
                WHERE i.detected_topic <> 'General SMC'
                GROUP BY i.detected_topic
                ORDER BY occurrences DESC, i.detected_topic ASC
                LIMIT 5
                """
            ).fetchall()
            common_mistakes = connection.execute(
                """
                SELECT mistake, COUNT(*) AS occurrences
                FROM dm_coach_mistakes
                GROUP BY mistake
                ORDER BY occurrences DESC, mistake ASC
                LIMIT 5
                """
            ).fetchall()
            recent_activity = connection.execute(
                """
                SELECT i.telegram_id, u.username, u.first_name, i.question,
                       i.detected_topic, i.created_at, i.mistakes_identified
                FROM dm_coaching_interactions i
                JOIN users u ON u.telegram_id = i.telegram_id
                ORDER BY i.created_at DESC, i.id DESC
                LIMIT 5
                """
            ).fetchall()
            return {
                **dict(counts),
                "common_questions": [dict(row) for row in common_questions],
                "weak_topics": [dict(row) for row in weak_topics],
                "common_mistakes": [dict(row) for row in common_mistakes],
                "recent_activity": [dict(row) for row in recent_activity],
            }
        finally:
            connection.close()

    def admin_members_page(
        self, page: int = 0, page_size: int = 10, *, sort: str = "joined"
    ) -> tuple[int, list[dict[str, Any]]]:
        ordering = {
            "joined": "u.started_at ASC, u.telegram_id ASC",
            "active": "u.last_interaction_at DESC, u.telegram_id ASC",
            "progress": "COALESCE(p.assessment_average, -1) DESC, "
            "u.last_interaction_at DESC, u.telegram_id ASC",
        }.get(sort)
        if ordering is None:
            raise ValueError("Unsupported admin member sort order.")
        safe_page_size = max(1, min(page_size, 25))
        safe_page = max(page, 0)
        connection = self._connect()
        try:
            total = int(
                connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT u.telegram_id, u.username, u.first_name, u.started_at,
                       u.last_interaction_at, u.last_checkin_at,
                       p.tests_completed, p.assessment_average,
                       p.latest_assessment_score, p.trades_journaled,
                       p.winning_trades, p.losing_trades
                FROM users u
                LEFT JOIN progress p ON p.telegram_id = u.telegram_id
                ORDER BY {ordering}
                LIMIT ? OFFSET ?
                """,
                (safe_page_size, safe_page * safe_page_size),
            ).fetchall()
            return total, [dict(row) for row in rows]
        finally:
            connection.close()

    def search_admin_members(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        clean_query = query.strip().lstrip("@")
        if not clean_query:
            return []
        connection = self._connect()
        try:
            if clean_query.isdigit():
                rows = connection.execute(
                    """
                    SELECT u.telegram_id, u.username, u.first_name, u.started_at,
                           u.last_interaction_at, p.tests_completed,
                           p.assessment_average, p.latest_assessment_score,
                           p.trades_journaled, p.winning_trades, p.losing_trades
                    FROM users u LEFT JOIN progress p ON p.telegram_id = u.telegram_id
                    WHERE u.telegram_id = ?
                    LIMIT ?
                    """,
                    (int(clean_query), max(1, min(limit, 20))),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT u.telegram_id, u.username, u.first_name, u.started_at,
                           u.last_interaction_at, p.tests_completed,
                           p.assessment_average, p.latest_assessment_score,
                           p.trades_journaled, p.winning_trades, p.losing_trades
                    FROM users u LEFT JOIN progress p ON p.telegram_id = u.telegram_id
                    WHERE lower(COALESCE(u.username, '')) = lower(?)
                       OR lower(COALESCE(u.first_name, '')) LIKE lower(?)
                       OR lower(COALESCE(u.username, '')) LIKE lower(?)
                    ORDER BY u.last_interaction_at DESC, u.telegram_id ASC
                    LIMIT ?
                    """,
                    (
                        clean_query,
                        f"%{clean_query}%",
                        f"%{clean_query}%",
                        max(1, min(limit, 20)),
                    ),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def admin_member_detail(
        self, telegram_id: int, assessment_page: int = 0, page_size: int = 8
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            safe_page_size = max(1, min(page_size, 20))
            safe_page = max(assessment_page, 0)
            user_row = connection.execute(
                """
                SELECT telegram_id, username, first_name, started_at,
                       last_interaction_at, last_checkin_at
                FROM users WHERE telegram_id = ?
                """,
                (telegram_id,),
            ).fetchone()
            if not user_row:
                return None
            assessment_stats = connection.execute(
                """
                SELECT COUNT(*) AS attempts, AVG(percentage) AS average_score
                FROM assessments WHERE telegram_id = ?
                """,
                (telegram_id,),
            ).fetchone()
            assessments = connection.execute(
                """
                SELECT score, total, percentage, strong_areas, weak_areas, completed_at
                FROM assessments WHERE telegram_id = ?
                ORDER BY completed_at DESC, id DESC LIMIT ? OFFSET ?
                """,
                (telegram_id, safe_page_size, safe_page * safe_page_size),
            ).fetchall()
            topic_rows = connection.execute(
                """
                SELECT a.topic, COUNT(*) AS attempts,
                       ROUND(100.0 * SUM(a.is_correct) / COUNT(*), 1) AS accuracy
                FROM assessment_answers a
                JOIN assessments s ON s.id = a.assessment_id
                WHERE s.telegram_id = ?
                GROUP BY a.topic
                ORDER BY accuracy DESC, a.topic ASC
                """,
                (telegram_id,),
            ).fetchall()
            trade_stats = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN result = 'Win' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result = 'Loss' THEN 1 ELSE 0 END) AS losses
                FROM trades WHERE telegram_id = ?
                """,
                (telegram_id,),
            ).fetchone()
            mistakes = connection.execute(
                """
                SELECT MIN(trim(mistake)) AS mistake, COUNT(*) AS occurrences
                FROM trades
                WHERE telegram_id = ?
                  AND trim(mistake) <> ''
                  AND lower(trim(mistake)) NOT IN ('none', 'n/a', 'no mistake')
                GROUP BY lower(trim(mistake))
                ORDER BY occurrences DESC, lower(trim(mistake)) ASC
                LIMIT 5
                """,
                (telegram_id,),
            ).fetchall()
            checkins = connection.execute(
                """
                SELECT trades_taken, winners, losses, discipline_summary,
                       next_focus, completed_at
                FROM weekly_checkins WHERE telegram_id = ?
                ORDER BY completed_at DESC, id DESC LIMIT 8
                """,
                (telegram_id,),
            ).fetchall()
            return {
                "user": dict(user_row),
                "assessment_count": assessment_stats["attempts"],
                "assessment_page": safe_page,
                "assessment_page_size": safe_page_size,
                "assessment_average": (
                    round(assessment_stats["average_score"], 1)
                    if assessment_stats["average_score"] is not None
                    else None
                ),
                "assessment_history": [dict(row) for row in assessments],
                "strong_topics": [
                    dict(row) for row in topic_rows if row["accuracy"] >= 70
                ],
                "weak_topics": [
                    dict(row) for row in topic_rows if row["accuracy"] < 70
                ],
                "topics_available": bool(topic_rows),
                "trade_total": trade_stats["total"],
                "wins": trade_stats["wins"] or 0,
                "losses": trade_stats["losses"] or 0,
                "common_mistakes": [dict(row) for row in mistakes],
                "weekly_checkins": [dict(row) for row in checkins],
            }
        finally:
            connection.close()

    def admin_trade_page(
        self,
        page: int = 0,
        page_size: int = 8,
        *,
        telegram_id: int | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        safe_page_size = max(1, min(page_size, 20))
        safe_page = max(page, 0)
        connection = self._connect()
        try:
            if telegram_id is None:
                total = int(
                    connection.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                )
                rows = connection.execute(
                    """
                    SELECT t.id, t.telegram_id, t.asset, t.direction, t.result,
                           t.mistake, t.created_at, u.username, u.first_name
                    FROM trades t
                    JOIN users u ON u.telegram_id = t.telegram_id
                    ORDER BY t.created_at DESC, t.id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (safe_page_size, safe_page * safe_page_size),
                ).fetchall()
            else:
                total = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM trades WHERE telegram_id = ?",
                        (telegram_id,),
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    """
                    SELECT t.id, t.telegram_id, t.asset, t.direction, t.result,
                           t.mistake, t.created_at, u.username, u.first_name
                    FROM trades t
                    JOIN users u ON u.telegram_id = t.telegram_id
                    WHERE t.telegram_id = ?
                    ORDER BY t.created_at DESC, t.id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (telegram_id, safe_page_size, safe_page * safe_page_size),
                ).fetchall()
            return total, [dict(row) for row in rows]
        finally:
            connection.close()

    def admin_trade_detail(self, trade_id: int) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT t.*, u.username, u.first_name
                FROM trades t JOIN users u ON u.telegram_id = t.telegram_id
                WHERE t.id = ?
                """,
                (trade_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    @staticmethod
    def _refresh_progress(
        connection: sqlite3.Connection, telegram_id: int
    ) -> None:
        assessment = connection.execute(
            """
            SELECT COUNT(*) AS count, AVG(percentage) AS average
            FROM assessments WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        latest = connection.execute(
            """
            SELECT score FROM assessments WHERE telegram_id = ?
            ORDER BY completed_at DESC, id DESC LIMIT 1
            """,
            (telegram_id,),
        ).fetchone()
        trade_stats = connection.execute(
            """
            SELECT
                COUNT(*) AS count,
                SUM(CASE WHEN result = 'Win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN result = 'Loss' THEN 1 ELSE 0 END) AS losses
            FROM trades WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()
        common_mistake = connection.execute(
            """
            SELECT mistake FROM trades
            WHERE telegram_id = ?
              AND trim(mistake) <> ''
              AND lower(trim(mistake)) NOT IN ('none', 'n/a', 'no mistake')
            GROUP BY lower(trim(mistake))
            ORDER BY COUNT(*) DESC, lower(trim(mistake)) ASC
            LIMIT 1
            """,
            (telegram_id,),
        ).fetchone()
        topic_rows = connection.execute(
            """
            SELECT topic, COUNT(*) AS attempts, SUM(is_correct) AS correct
            FROM assessment_answers a
            JOIN assessments s ON s.id = a.assessment_id
            WHERE s.telegram_id = ?
            GROUP BY topic
            ORDER BY topic ASC
            """,
            (telegram_id,),
        ).fetchall()
        topic_accuracy = [
            (row["topic"], row["correct"] / row["attempts"])
            for row in topic_rows
            if row["attempts"]
        ]
        strongest = (
            max(topic_accuracy, key=lambda item: (item[1], item[0]))[0]
            if topic_accuracy
            else None
        )
        weakest = (
            min(topic_accuracy, key=lambda item: (item[1], item[0]))[0]
            if topic_accuracy
            else None
        )
        weekly_count = connection.execute(
            "SELECT COUNT(*) FROM weekly_checkins WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO progress (
                telegram_id, tests_completed, assessment_average,
                latest_assessment_score, trades_journaled, winning_trades,
                losing_trades, most_common_mistake, strongest_topic, weakest_topic,
                weekly_checkins_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                tests_completed = excluded.tests_completed,
                assessment_average = excluded.assessment_average,
                latest_assessment_score = excluded.latest_assessment_score,
                trades_journaled = excluded.trades_journaled,
                winning_trades = excluded.winning_trades,
                losing_trades = excluded.losing_trades,
                most_common_mistake = excluded.most_common_mistake,
                strongest_topic = excluded.strongest_topic,
                weakest_topic = excluded.weakest_topic,
                weekly_checkins_count = excluded.weekly_checkins_count,
                updated_at = excluded.updated_at
            """,
            (
                telegram_id,
                assessment["count"],
                round(assessment["average"], 1) if assessment["average"] is not None else None,
                latest["score"] if latest else None,
                trade_stats["count"] or 0,
                trade_stats["wins"] or 0,
                trade_stats["losses"] or 0,
                common_mistake["mistake"] if common_mistake else None,
                strongest,
                weakest,
                weekly_count,
                utc_now(),
            ),
        )