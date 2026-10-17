"""SQLite repository for members, assessments, journals, progress, and reminders."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
                        zoom_class_reminders_enabled INTEGER NOT NULL DEFAULT 0
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
                    """
                )
                self._ensure_user_column(
                    connection,
                    "zoom_class_reminders_enabled",
                    "INTEGER NOT NULL DEFAULT 0",
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
                ORDER BY telegram_id
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def class_reminder_recipients(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT telegram_id, chat_id, first_name
                FROM users
                WHERE started_at IS NOT NULL
                  AND is_private = 1
                  AND chat_id IS NOT NULL
                  AND zoom_class_reminders_enabled = 1
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