"""Private, optional photo prompts for the scheduled USD/gold briefs."""

from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .news_brief_image_analysis import (
    GeminiNewsImageAnalysisService,
    GeminiNewsImageError,
    MAX_IMAGE_BYTES,
)
from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)
WAT = ZoneInfo("Africa/Lagos")
PHOTO_PROMPT_LEAD_SECONDS = 30 * 60
_MAX_TELEGRAM_MESSAGE_UTF16 = 4096
_ALLOWED_SOURCE_HOSTS = frozenset(
    {
        "www.bea.gov",
        "apps.bea.gov",
        "www.census.gov",
        "www.bls.gov",
        "www.federalreserve.gov",
        "www.dol.gov",
    }
)
_SOURCE_STATUS_KEYS = {
    "U.S. Bureau of Economic Analysis": "BEA",
    "U.S. Bureau of Labor Statistics": "BLS",
    "U.S. Census Bureau": "Census",
    "Federal Reserve": "Federal Reserve",
    "U.S. Department of Labor": "DOL",
}
_PHOTO_CALLBACK = re.compile(
    r"newsbrief:(photo|none):(daily|weekly):(\d{4}-\d{2}-\d{2})"
)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("photo_review_time_must_be_timezone_aware")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _event_date(record: dict) -> date | None:
    event_at = _parse_timestamp(record.get("event_at_utc"))
    if event_at is not None:
        return event_at.astimezone(WAT).date()
    raw = str(record.get("release_date_text") or "").strip()
    for pattern in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _source_url_is_allowed(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_SOURCE_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def build_verified_image_evidence(
    brief_type: str,
    brief_date: date,
    records: list[dict],
    source_status: list[dict],
    *,
    now: datetime,
) -> list[dict]:
    """Return only fresh official records already eligible for a brief."""
    if now.tzinfo is None or brief_type not in {"daily", "weekly"}:
        return []
    observed = now.astimezone(timezone.utc)
    statuses = {str(row.get("source_name")): row for row in source_status}
    allowed_sources = (
        {"U.S. Bureau of Economic Analysis"}
        if brief_type == "daily"
        else {
            "U.S. Bureau of Economic Analysis",
            "U.S. Bureau of Labor Statistics",
            "U.S. Census Bureau",
            "Federal Reserve",
        }
    )
    end_date = brief_date if brief_type == "daily" else brief_date + timedelta(days=6)
    result: list[dict] = []
    for record in records:
        source = str(record.get("source_name") or "")
        if source not in allowed_sources:
            continue
        status_key = _SOURCE_STATUS_KEYS.get(source)
        source_row = statuses.get(status_key or "", {})
        checked_at = _parse_timestamp(source_row.get("checked_at_utc"))
        retrieved_at = _parse_timestamp(record.get("retrieved_at_utc"))
        if (
            source_row.get("status") != "verified_schedule"
            or checked_at is None
            or not timedelta(0) <= observed - checked_at <= timedelta(hours=24)
            or retrieved_at is None
            or not timedelta(0) <= observed - retrieved_at <= timedelta(hours=24)
            or not _source_url_is_allowed(record.get("source_url"))
        ):
            continue

        verification = str(record.get("verification_status") or "")
        if source == "U.S. Census Bureau":
            if verification != "date_time_listed_timezone_unverified":
                continue
        elif source == "Federal Reserve":
            if verification != "verified_meeting_window_release_time_unavailable":
                continue
        elif verification != "verified_schedule":
            continue
        event_date = _event_date(record)
        if event_date is None or not brief_date <= event_date <= end_date:
            continue
        if brief_type == "daily" and (
            source != "U.S. Bureau of Economic Analysis"
            or _parse_timestamp(record.get("event_at_utc")) is None
            or record.get("timezone_status") != "verified_explicit_utc_offset"
        ):
            continue
        result.append(dict(record))
        if len(result) >= 40:
            break
    return result


def append_verified_image_highlights(
    report: str,
    evidence: list[dict],
    event_ids: list[str] | tuple[str, ...],
) -> str:
    """Add a short source-backed highlight, never a claim from the image."""
    selected = set(event_ids)
    rows = [
        item
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("external_id"), str)
        and item["external_id"] in selected
        and _source_url_is_allowed(item.get("source_url"))
    ][:3]
    if not rows:
        return report
    lines = [
        "",
        "━━━━━━━━━━━━━━",
        "",
        "📷 <b>RELATED EVENTS</b>",
    ]
    for item in rows:
        title = html.escape(str(item.get("title") or "U.S. release")[:240])
        event_date = _event_date(item)
        if event_date is None:
            continue
        date_text = event_date.strftime("%a, %d %b %Y")
        event_at = _parse_timestamp(item.get("event_at_utc"))
        timezone_status = str(item.get("timezone_status") or "")
        timezone_verified = (
            timezone_status == "verified_explicit_utc_offset"
            or timezone_status.startswith("verified_source_timezone:")
        )
        time_text = (
            f" · {event_at.astimezone(WAT).strftime('%H:%M WAT')}"
            if event_at is not None and timezone_verified
            else ""
        )
        lines.extend(
            [
                f"• {date_text} — {title}{time_text}",
            ]
        )
    if len(lines) == 4:
        return report
    updated = report.rstrip() + "\n" + "\n".join(lines)
    if _utf16_length(updated) > _MAX_TELEGRAM_MESSAGE_UTF16:
        return report
    return updated


class NewsBriefPhotoPrompts:
    """Privately preview scheduled briefs and review an optional admin image."""

    def __init__(
        self,
        api: TelegramAPI,
        database_path: str | Path,
        *,
        admin_id: int | None,
        image_analyzer: GeminiNewsImageAnalysisService | None = None,
    ) -> None:
        self.api = api
        self.database_path = Path(database_path)
        self.admin_id = admin_id
        self.image_analyzer = image_analyzer
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
                    scheduled_at_utc TEXT,
                    preview_content TEXT,
                    verified_evidence_json TEXT,
                    matched_event_ids_json TEXT,
                    image_analysis_status TEXT,
                    PRIMARY KEY (brief_type, brief_date)
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(news_brief_photo_reviews)"
                ).fetchall()
            }
            for column, definition in (
                ("scheduled_at_utc", "TEXT"),
                ("preview_content", "TEXT"),
                ("verified_evidence_json", "TEXT"),
                ("matched_event_ids_json", "TEXT"),
                ("image_analysis_status", "TEXT"),
            ):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE news_brief_photo_reviews "
                        f"ADD COLUMN {column} {definition}"
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
        preview_content: str,
        verified_evidence: list[dict] | None = None,
    ) -> bool:
        if brief_type not in {"daily", "weekly"} or self.admin_id is None:
            return False
        if (
            not isinstance(preview_content, str)
            or not preview_content.strip()
            or _utf16_length(preview_content) > _MAX_TELEGRAM_MESSAGE_UTF16
        ):
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
                    (brief_type, brief_date, status, created_at_utc, updated_at_utc,
                     scheduled_at_utc, preview_content, verified_evidence_json,
                     matched_event_ids_json, image_analysis_status)
                VALUES (?, ?, 'prompting', ?, ?, ?, ?, ?, '[]', 'not_started')
                """,
                (
                    brief_type,
                    brief_date.isoformat(),
                    timestamp,
                    timestamp,
                    _timestamp(scheduled),
                    preview_content,
                    json.dumps(
                        verified_evidence or [],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
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
        heading = (
            "PREVIEW — NOT PUBLISHED\n"
            f"{label} USD & Gold brief for {brief_date.strftime('%A, %d %B %Y')}\n"
            f"Destination: {destination}\n"
            f"Scheduled: {local_schedule.strftime('%H:%M WAT')}"
        )
        prompt = (
            "This review arrives 30 minutes before publication. Would you like to "
            "add a picture? Tap “Add picture”, then send one image privately to "
            "this bot. Gemini will only match it to currently "
            "verified official calendar records; it cannot supply or change "
            "figures. If you do not reply or add a picture, the brief will still "
            "publish text-only at the scheduled time if final source and destination "
            "checks pass."
        )
        try:
            self.api.send_message(int(self.admin_id), heading)
            self.api.send_message(
                int(self.admin_id),
                preview_content,
                parse_mode="HTML",
            )
            self.api.send_message(int(self.admin_id), prompt, markup)
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
        if not self._before_publication(brief_type, brief_date, current):
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
        if not self._before_publication(brief_type, brief_date, current):
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

        with closing(sqlite3.connect(self.database_path)) as connection:
            review = connection.execute(
                """
                SELECT verified_evidence_json, preview_content
                FROM news_brief_photo_reviews
                WHERE brief_type=? AND brief_date=?
                """,
                (brief_type, brief_date.isoformat()),
            ).fetchone()
        evidence: list[dict] = []
        preview = ""
        if review is not None:
            try:
                decoded = json.loads(str(review[0] or "[]"))
                evidence = decoded if isinstance(decoded, list) else []
            except json.JSONDecodeError:
                evidence = []
            preview = str(review[1] or "")
        if not evidence or self.image_analyzer is None:
            self._record_image_rejection(
                brief_type, brief_date, "unavailable", current
            )
            self.api.send_message(
                chat_id,
                "I couldn't verify this picture against fresh official calendar "
                "records, so I won't use it to change or accompany the news. The "
                "text brief remains on schedule.",
            )
            return True

        image_check_started = time.monotonic()
        try:
            file_info = self.api.get_file(file_id)
            file_path = file_info.get("file_path")
            if not isinstance(file_path, str):
                raise TelegramAPIError("Telegram file path is unavailable.")
            image_bytes, mime_type = self.api.download_file(
                file_path,
                max_bytes=MAX_IMAGE_BYTES,
            )
            analysis = self.image_analyzer.analyze(
                image_bytes,
                mime_type,
                evidence,
            )
            allowed = {
                str(item.get("external_id"))
                for item in evidence
                if isinstance(item, dict) and item.get("external_id")
            }
            matched_ids = [
                event_id
                for event_id in analysis.relevant_event_ids
                if event_id in allowed
            ][:3]
        except (TelegramAPIError, GeminiNewsImageError, OSError, ValueError):
            self._record_image_rejection(
                brief_type, brief_date, "failed", current
            )
            self.api.send_message(
                chat_id,
                "I couldn't safely read and check that picture this time. It won't "
                "change the news or be posted; the text brief remains on schedule.",
            )
            logger.warning("Optional USD/gold brief image review failed.")
            return True
        except Exception:
            self._record_image_rejection(
                brief_type, brief_date, "failed", current
            )
            self.api.send_message(
                chat_id,
                "I couldn't safely read and check that picture this time. It won't "
                "change the news or be posted; the text brief remains on schedule.",
            )
            logger.warning("Unexpected failure while checking a brief image.")
            return True

        if not matched_ids:
            self._record_image_rejection(
                brief_type, brief_date, "unmatched", current
            )
            self.api.send_message(
                chat_id,
                "The picture did not clearly match a currently verified official "
                "calendar record. I won't use it or add its claims to the brief. "
                "The text brief remains on schedule.",
            )
            return True

        completed_at = current + timedelta(
            seconds=max(0.0, time.monotonic() - image_check_started)
        )
        if (
            not self._before_publication(brief_type, brief_date, completed_at)
            or self._status(brief_type, brief_date)
            not in {"awaiting_photo", "photo_attached"}
        ):
            self._clear_selection()
            self.api.send_message(
                chat_id,
                "The scheduled time arrived while I was checking the picture. It "
                "was not attached, and the brief was not delayed.",
            )
            return True

        updated_preview = append_verified_image_highlights(
            preview,
            evidence,
            matched_ids,
        )
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            update_result = connection.execute(
                """
                UPDATE news_brief_photo_reviews
                SET status='photo_attached', photo_file_id=?, updated_at_utc=?,
                    matched_event_ids_json=?, image_analysis_status='matched',
                    preview_content=?
                WHERE brief_type=? AND brief_date=?
                    AND status IN ('awaiting_photo', 'photo_attached')
                """,
                (
                    file_id,
                    _timestamp(current),
                    json.dumps(matched_ids, separators=(",", ":")),
                    updated_preview,
                    brief_type,
                    brief_date.isoformat(),
                ),
            )
            if update_result.rowcount == 1:
                connection.execute(
                    "DELETE FROM news_brief_photo_selection WHERE admin_id=?",
                    (self.admin_id,),
                )
        if update_result.rowcount != 1:
            self.api.send_message(
                chat_id,
                "The brief changed status while I was checking the picture. It "
                "was not attached, and the scheduled post was not delayed.",
            )
            return True
        self.api.send_message(
            chat_id,
            "The picture was matched to calendar events. The revised preview "
            "follows; its event details remain limited to verified calendar data.",
        )
        self.api.send_message(chat_id, "UPDATED PREVIEW — NOT PUBLISHED")
        self.api.send_message(chat_id, updated_preview, parse_mode="HTML")
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

    def publication_media(
        self,
        brief_type: str,
        brief_date: date,
        report: str,
        records: list[dict],
        source_status: list[dict],
        *,
        now: datetime,
    ) -> tuple[str, str | None]:
        """Revalidate image-matched IDs against current official records."""
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT status, photo_file_id, matched_event_ids_json
                FROM news_brief_photo_reviews
                WHERE brief_type=? AND brief_date=?
                """,
                (brief_type, brief_date.isoformat()),
            ).fetchone()
        if not row or row[0] != "photo_attached":
            return report, None
        try:
            matched = json.loads(str(row[2] or "[]"))
        except json.JSONDecodeError:
            matched = []
        if not isinstance(matched, list):
            matched = []
        current_evidence = build_verified_image_evidence(
            brief_type,
            brief_date,
            records,
            source_status,
            now=now,
        )
        current_ids = {
            str(item.get("external_id"))
            for item in current_evidence
            if item.get("external_id")
        }
        valid_ids = [
            item
            for item in matched
            if isinstance(item, str) and item in current_ids
        ]
        if not valid_ids:
            self._exclude_unverified_photo(brief_type, brief_date, now)
            return report, None
        updated_report = append_verified_image_highlights(
            report,
            current_evidence,
            valid_ids,
        )
        photo = row[1] if isinstance(row[1], str) and row[1] else None
        return updated_report, photo

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

    def has_review(self, brief_type: str, brief_date: date) -> bool:
        return self._status(brief_type, brief_date) is not None

    def _before_publication(
        self,
        brief_type: str,
        brief_date: date,
        current: datetime,
    ) -> bool:
        if current.tzinfo is None:
            return False
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT scheduled_at_utc FROM news_brief_photo_reviews
                WHERE brief_type=? AND brief_date=?
                """,
                (brief_type, brief_date.isoformat()),
            ).fetchone()
        scheduled = _parse_timestamp(row[0]) if row else None
        return scheduled is not None and current.astimezone(timezone.utc) < scheduled

    def _record_image_rejection(
        self,
        brief_type: str,
        brief_date: date,
        reason: str,
        now: datetime,
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                UPDATE news_brief_photo_reviews
                SET status='awaiting_photo', photo_file_id=NULL,
                    matched_event_ids_json='[]', image_analysis_status=?,
                    updated_at_utc=?
                WHERE brief_type=? AND brief_date=?
                """,
                (
                    reason,
                    _timestamp(now),
                    brief_type,
                    brief_date.isoformat(),
                ),
            )
            connection.execute(
                "DELETE FROM news_brief_photo_selection WHERE admin_id=?",
                (self.admin_id,),
            )

    def _exclude_unverified_photo(
        self,
        brief_type: str,
        brief_date: date,
        now: datetime,
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            changed = connection.execute(
                """
                UPDATE news_brief_photo_reviews
                SET status='photo_unverified', photo_file_id=NULL,
                    image_analysis_status='source_no_longer_verified',
                    updated_at_utc=?
                WHERE brief_type=? AND brief_date=? AND status='photo_attached'
                """,
                (_timestamp(now), brief_type, brief_date.isoformat()),
            ).rowcount
        if changed and self.admin_id is not None:
            try:
                self.api.send_message(
                    int(self.admin_id),
                    "I left the picture out because its official calendar record "
                    "was no longer fresh and verified at publication time. The "
                    "text brief continues through its normal source and "
                    "destination checks.",
                )
            except Exception:
                logger.warning(
                    "Could not notify admin that a brief image was excluded."
                )

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
