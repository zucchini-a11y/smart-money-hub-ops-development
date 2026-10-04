"""Local SQLite storage for completed assessment scores."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DATABASE_PATH = Path("data/smart_money_hub.sqlite3")


class ScoreStore:
    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10)

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assessment_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER NOT NULL,
                        username TEXT,
                        score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 10),
                        percentage INTEGER NOT NULL CHECK (percentage BETWEEN 0 AND 100),
                        completed_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS assessment_results_member_date
                    ON assessment_results (telegram_id, completed_at DESC)
                    """
                )
        finally:
            connection.close()

    def save_result(
        self,
        *,
        telegram_id: int,
        username: str | None,
        score: int,
        percentage: int,
        completed_at: str | None = None,
    ) -> None:
        timestamp = completed_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        connection = self._connect()
        try:
            with connection:
                connection.execute(
                    """
                    INSERT INTO assessment_results
                        (telegram_id, username, score, percentage, completed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (telegram_id, username, score, percentage, timestamp),
                )
        finally:
            connection.close()