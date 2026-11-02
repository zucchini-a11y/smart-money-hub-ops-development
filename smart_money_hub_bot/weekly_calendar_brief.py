"""Safe weekly official-source USD/XAU calendar publishing."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .daily_calendar_brief import (
    CALENDAR_STALE_AFTER,
    TELEGRAM_MESSAGE_LIMIT_UTF16,
)
from .economic_calendar_phase1 import (
    OfficialCalendarRepository,
    fetch_and_store_official_schedules,
)
from .group_features import (
    DEFAULT_EDUCATION_GROUP_ID,
    EDUCATION_ANNOUNCEMENTS_THREAD_ID,
)
from .brief_photo_review import (
    NewsBriefPhotoPrompts,
    build_verified_image_evidence,
    send_brief_with_optional_photo,
)
from .event_impact_estimator import (
    GeminiEventImpactEstimator,
    event_impact_label,
)
from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)
WAT = ZoneInfo("Africa/Lagos")
WEEKLY_BRIEF_TIME = time(0, 0)
WEEKLY_BRIEF_GRACE = timedelta(minutes=15)
SOURCE_REFRESH_REUSE_WINDOW = timedelta(minutes=5)
_REQUIRED_SOURCES = {"BEA", "Census", "BLS", "Federal Reserve", "DOL"}
_ALLOWED_HOSTS = {
    "apps.bea.gov",
    "www.bea.gov",
    "www.bls.gov",
    "www.census.gov",
    "www.federalreserve.gov",
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Weekly brief timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed) if parsed.tzinfo else None


def _fresh_timestamp(value: object, now_utc: datetime) -> bool:
    parsed = _parse_utc(value)
    if parsed is None:
        return False
    age = now_utc - parsed
    return timedelta(0) <= age <= CALENDAR_STALE_AFTER


def _safe_source_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def _event_date(record: dict) -> date | None:
    event_at = _parse_utc(record.get("event_at_utc"))
    if event_at is not None:
        return event_at.astimezone(WAT).date()
    raw = str(record.get("release_date_text") or "")
    for pattern in ("%B %d, %Y", "%a, %d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    meeting = re.fullmatch(
        r"([A-Za-z]+) (\d+)(?:[–-]\d+), (\d{4})",
        raw,
    )
    if meeting:
        try:
            return datetime.strptime(
                f"{meeting.group(1)} {meeting.group(2)} {meeting.group(3)}",
                "%B %d %Y",
            ).date()
        except ValueError:
            return None
    return None


def verified_weekly_events(
    week_start: date,
    records: list[dict],
    source_status: list[dict],
    *,
    now: datetime,
) -> list[tuple[date, datetime | None, dict]]:
    """Select only fresh official records eligible for a weekly calendar."""
    if week_start.weekday() != 0:
        raise ValueError("Weekly brief must start on a Monday.")
    now_utc = _utc(now)
    week_end = week_start + timedelta(days=6)
    statuses = {str(row.get("source_name")): row for row in source_status}

    def source_verified(name: str) -> bool:
        status = statuses.get(name, {})
        return (
            status.get("status") == "verified_schedule"
            and _fresh_timestamp(status.get("checked_at_utc"), now_utc)
        )

    eligible_sources = {
        "U.S. Bureau of Economic Analysis",
        "U.S. Bureau of Labor Statistics",
        "U.S. Census Bureau",
        "Federal Reserve",
    }
    events: list[tuple[date, datetime | None, dict]] = []
    for record in records:
        source = str(record.get("source_name") or "")
        if source not in eligible_sources:
            continue
        source_key = {
            "U.S. Bureau of Economic Analysis": "BEA",
            "U.S. Bureau of Labor Statistics": "BLS",
            "U.S. Census Bureau": "Census",
            "Federal Reserve": "Federal Reserve",
        }[source]
        if not source_verified(source_key):
            continue
        if not _fresh_timestamp(record.get("retrieved_at_utc"), now_utc):
            continue
        if not _safe_source_url(record.get("source_url")):
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
        if event_date is None or not week_start <= event_date <= week_end:
            continue
        event_at = _parse_utc(record.get("event_at_utc"))
        events.append((event_date, event_at, record))

    events.sort(
        key=lambda item: (
            item[0],
            item[1] or datetime.max.replace(tzinfo=timezone.utc),
            str(item[2].get("title") or ""),
        )
    )
    return events


def build_weekly_usd_gold_brief(
    week_start: date,
    records: list[dict],
    source_status: list[dict],
    *,
    now: datetime,
    impact_estimates: dict[str, str] | None = None,
) -> str:
    """Render a concise weekly event list with plain impact labels."""
    if week_start.weekday() != 0:
        raise ValueError("Weekly brief must start on a Monday.")
    now_utc = _utc(now)
    week_end = week_start + timedelta(days=6)

    events = verified_weekly_events(
        week_start,
        records,
        source_status,
        now=now_utc,
    )
    lines = [
        "🌍 <b>SMART MONEY HUB | WEEKLY NEWS OUTLOOK 📊</b>",
        f"📅 Week: {week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}",
        "",
        "━━━━━━━━━━━━━━",
    ]

    by_date: dict[date, list[tuple[datetime | None, dict]]] = {}
    for event_date, event_at, record in events:
        by_date.setdefault(event_date, []).append((event_at, record))

    for day_offset in range(5):
        event_date = week_start + timedelta(days=day_offset)
        lines.extend(
            [
                "━━━━━━━━━━━━━━",
                "",
                f"🗓️ <b>{event_date.strftime('%A').upper()} · "
                f"{event_date.strftime('%d %b')}</b>",
            ]
        )
        daily_events = by_date.get(event_date, [])
        if not daily_events:
            lines.append("No calendar entries listed.")
        for event_at, record in daily_events:
            title_text = str(record.get("title") or "U.S. release")
            title = html.escape(title_text)
            date_text = event_date.strftime("%a, %d %b")
            time_text = (
                f" · {event_at.astimezone(WAT).strftime('%H:%M WAT')}"
                if event_at is not None
                else ""
            )
            lines.extend(
                [
                    f"📰 <b>{date_text} — {title}</b>{time_text}",
                    event_impact_label(record, impact_estimates),
                ]
            )
        lines.append("")

    weekend_events = [
        (event_date, event_at, record)
        for event_date, event_at, record in events
        if event_date.weekday() >= 5
    ]
    if weekend_events:
        lines.extend(["━━━━━━━━━━━━━━", "", "🗓️ <b>WEEKEND</b>"])
        for event_date, event_at, record in weekend_events:
            title = html.escape(str(record.get("title") or "U.S. release"))
            time_text = (
                f" · {event_at.astimezone(WAT).strftime('%H:%M WAT')}"
                if event_at is not None
                else ""
            )
            lines.extend(
                [
                    f"📰 <b>{event_date.strftime('%a, %d %b')} — {title}</b>{time_text}",
                    event_impact_label(record, impact_estimates),
                ]
            )

    lines.extend(
        [
            "━━━━━━━━━━━━━━",
            "",
            "⚠️ News can bring volatility. Wait for your confirmation before entering.",
            "",
            "<b>NO CONFIRMATION, NO ENTRY. 🎯</b>",
            "",
            "<b>SMART MONEY HUB</b>",
            "Learn • Confirm • Execute • Grow",
        ]
    )
    report = "\n".join(lines)
    if len(report.encode("utf-16-le")) // 2 > TELEGRAM_MESSAGE_LIMIT_UTF16:
        raise ValueError("weekly_brief_exceeds_telegram_limit")
    return report


class WeeklyCalendarBriefStore:
    """Persistent at-most-once state keyed by the Monday WAT week start."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usd_gold_weekly_brief_runs (
                    week_start_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 1,
                    failure_category TEXT,
                    content_sha256 TEXT,
                    content TEXT,
                    telegram_message_id INTEGER,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )

    def reserve(self, week_start: date, now: datetime) -> tuple[bool, str | None]:
        timestamp = _utc(now).isoformat(timespec="seconds")
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO usd_gold_weekly_brief_runs
                    (week_start_date, status, attempts, created_at_utc, updated_at_utc)
                VALUES (?, 'sending', 1, ?, ?)
                """,
                (week_start.isoformat(), timestamp, timestamp),
            )
            if cursor.rowcount == 1:
                return True, None
            row = connection.execute(
                "SELECT status FROM usd_gold_weekly_brief_runs WHERE week_start_date=?",
                (week_start.isoformat(),),
            ).fetchone()
            return False, str(row[0]) if row else "unknown"

    def finish(
        self,
        week_start: date,
        *,
        status: str,
        now: datetime,
        content: str | None = None,
        message_id: int | None = None,
        failure_category: str | None = None,
    ) -> None:
        timestamp = _utc(now).isoformat(timespec="seconds")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                UPDATE usd_gold_weekly_brief_runs
                SET status=?, failure_category=?, content_sha256=?, content=?,
                    telegram_message_id=?, updated_at_utc=?
                WHERE week_start_date=?
                """,
                (
                    status,
                    failure_category,
                    digest,
                    content,
                    message_id,
                    timestamp,
                    week_start.isoformat(),
                ),
            )

    def get(self, week_start: date) -> dict | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM usd_gold_weekly_brief_runs WHERE week_start_date=?",
                (week_start.isoformat(),),
            ).fetchone()
            return dict(row) if row else None


class WeeklyCalendarBriefPublisher:
    """Publish a weekly source-verified calendar on Monday at 00:00 WAT."""

    def __init__(
        self,
        api: TelegramAPI,
        database_path: str | Path,
        *,
        admin_id: int | None,
        group_id: int | None,
        thread_id: int = EDUCATION_ANNOUNCEMENTS_THREAD_ID,
        photo_prompts: NewsBriefPhotoPrompts | None = None,
        impact_estimator: GeminiEventImpactEstimator | None = None,
        source_refresh=fetch_and_store_official_schedules,
    ) -> None:
        self.api = api
        self.database_path = Path(database_path)
        self.admin_id = admin_id
        self.group_id = group_id
        self.thread_id = thread_id
        self.photo_prompts = photo_prompts
        self.impact_estimator = impact_estimator
        self.calendar = OfficialCalendarRepository(database_path)
        self.store = WeeklyCalendarBriefStore(database_path)
        self.source_refresh = source_refresh

    def dispatch_photo_prompt(self, now: datetime | None = None) -> bool:
        if self.photo_prompts is None:
            return False
        current = _utc(now or datetime.now(timezone.utc))
        local_now = current.astimezone(WAT)
        if local_now.weekday() != 6 or local_now.hour != 23 or local_now.minute < 30:
            return False
        brief_date = local_now.date() + timedelta(days=1)
        if self.photo_prompts.has_review("weekly", brief_date):
            return False
        scheduled_at = datetime.combine(brief_date, WEEKLY_BRIEF_TIME, tzinfo=WAT)
        statuses = self.calendar.list_source_status()
        bea = next(
            (row for row in statuses if row.get("source_name") == "BEA"),
            None,
        )
        if not bea or not _fresh_timestamp(bea.get("checked_at_utc"), current):
            self.source_refresh(self.database_path, now=current)
            statuses = self.calendar.list_source_status()
        records = self.calendar.list_records()
        eligible_events = verified_weekly_events(
            brief_date, records, statuses, now=current
        )
        estimates = self._estimate_impacts(
            [record for _, _, record in eligible_events]
        )
        report = build_weekly_usd_gold_brief(
            brief_date,
            records,
            statuses,
            now=current,
            impact_estimates=estimates,
        )
        evidence = build_verified_image_evidence(
            "weekly",
            brief_date,
            records,
            statuses,
            now=current,
        )
        return self.photo_prompts.send_prompt_if_due(
            "weekly",
            brief_date,
            scheduled_at,
            destination="Education Suite Announcements topic",
            now=current,
            preview_content=report,
            verified_evidence=evidence,
        )

    def dispatch(self, now: datetime | None = None) -> str:
        current = _utc(now or datetime.now(timezone.utc))
        local_now = current.astimezone(WAT)
        if local_now.weekday() != 0:
            return "not_due"
        if local_now.time().replace(tzinfo=None) < WEEKLY_BRIEF_TIME:
            return "not_due"
        if self.admin_id is None or self.group_id is None:
            return "disabled"

        week_start = local_now.date()
        reserved, prior_status = self.store.reserve(week_start, current)
        if not reserved:
            if prior_status == "sending":
                self.store.finish(
                    week_start,
                    status="delivery_unknown",
                    now=current,
                    failure_category="interrupted_send_state",
                )
                self._notify_admin(
                    "Weekly USD/Gold brief delivery is uncertain after an "
                    "interrupted send. Check the Education Suite Announcements "
                    "topic before any retry.",
                )
                return "delivery_unknown"
            return f"already_{prior_status}"

        scheduled_at = datetime.combine(week_start, WEEKLY_BRIEF_TIME, tzinfo=WAT)
        if current > scheduled_at.astimezone(timezone.utc) + WEEKLY_BRIEF_GRACE:
            self.store.finish(
                week_start,
                status="skipped",
                now=current,
                failure_category="missed_publication_window",
            )
            logger.warning(
                "Weekly USD/Gold brief skipped after its WAT publication window "
                "(week=%s, no_channel_send=true).",
                week_start.isoformat(),
            )
            return "skipped_late"

        try:
            statuses = self.calendar.list_source_status()
            if not self._sources_checked_recently(statuses, current):
                self.source_refresh(self.database_path, now=current)
                statuses = self.calendar.list_source_status()
            bea = next((row for row in statuses if row.get("source_name") == "BEA"), None)
            if (
                not bea
                or bea.get("status") != "verified_schedule"
                or not _fresh_timestamp(bea.get("checked_at_utc"), current)
            ):
                self.store.finish(
                    week_start,
                    status="held",
                    now=current,
                    failure_category="bea_source_not_verified",
                )
                self._notify_admin(
                    "The weekly USD/Gold brief was held: BEA's official schedule "
                    "could not be confirmed fresh. Nothing was sent.",
                )
                return "held_source_unverified"

            records = self.calendar.list_records()
            eligible_events = verified_weekly_events(
                week_start, records, statuses, now=current
            )
            estimates = self._estimate_impacts(
                [record for _, _, record in eligible_events]
            )
            report = build_weekly_usd_gold_brief(
                week_start,
                records,
                statuses,
                now=current,
                impact_estimates=estimates,
            )
            self._verify_destination()
            if self.photo_prompts is not None:
                report, photo_file_id = self.photo_prompts.publication_media(
                    "weekly",
                    week_start,
                    report,
                    records,
                    statuses,
                    now=current,
                )
            else:
                photo_file_id = None
            message_id, photo_status = send_brief_with_optional_photo(
                self.api,
                int(self.group_id),
                report,
                photo_file_id=photo_file_id,
                message_thread_id=self.thread_id,
                photo_caption="📊 SMART MONEY HUB | WEEKLY NEWS OUTLOOK",
            )
            self.store.finish(
                week_start,
                status="published",
                now=datetime.now(timezone.utc),
                content=report,
                message_id=message_id,
            )
            if self.photo_prompts is not None:
                self.photo_prompts.mark_published("weekly", week_start, now=current)
            if photo_status not in {"not_requested", "sent"}:
                self._notify_admin(
                    "The weekly brief text was published in Education Suite "
                    "Announcements, but its optional picture was not confirmed. "
                    "Check the topic before taking action; the bot will not resend it."
                )
            incomplete = [
                name
                for name in ("BLS", "Census", "Federal Reserve", "DOL")
                if not any(
                    row.get("source_name") == name
                    and row.get("status") == "verified_schedule"
                    and _fresh_timestamp(row.get("checked_at_utc"), current)
                    for row in statuses
                )
            ]
            if incomplete:
                self._notify_admin(
                    "The weekly USD/Gold brief was published with a partial-coverage "
                    f"note. Unverified sources: {', '.join(incomplete)}."
                )
            logger.info(
                "Weekly USD/Gold brief published (week=%s, message_confirmed=true).",
                week_start.isoformat(),
            )
            return "published"
        except TelegramAPIError as error:
            status = "delivery_unknown" if error.delivery_unknown else "held"
            failure = (
                "telegram_delivery_unknown"
                if error.delivery_unknown
                else f"telegram_http_{error.http_status}"
                if error.http_status
                else "telegram_send_failed"
            )
            self.store.finish(
                week_start,
                status=status,
                now=current,
                failure_category=failure,
            )
            self._notify_admin(
                "The weekly USD/Gold brief was not confirmed as published. "
                "Automatic resend is disabled to prevent duplicates."
            )
            return status
        except (ValueError, OSError, sqlite3.Error) as error:
            failure = (
                "weekly_brief_exceeds_telegram_limit"
                if str(error) == "weekly_brief_exceeds_telegram_limit"
                else "weekly_brief_preparation_failed"
            )
            self.store.finish(
                week_start,
                status="held",
                now=current,
                failure_category=failure,
            )
            self._notify_admin(
                "The weekly USD/Gold brief was held during preparation or "
                "destination verification. Nothing was sent."
            )
            logger.warning("Weekly USD/Gold brief held category=%s.", failure)
            return "held"
        except Exception:
            self.store.finish(
                week_start,
                status="held",
                now=current,
                failure_category="unexpected_weekly_brief_error",
            )
            self._notify_admin(
                "The weekly USD/Gold brief was held after an unexpected error. "
                "Nothing was sent."
            )
            logger.exception("Weekly USD/Gold brief dispatch failed safely.")
            return "held"

    def _verify_destination(self) -> None:
        if (
            int(self.group_id or 0) != DEFAULT_EDUCATION_GROUP_ID
            or int(self.thread_id) != EDUCATION_ANNOUNCEMENTS_THREAD_ID
        ):
            raise ValueError("weekly_brief_destination_mismatch")
        bot = self.api.get_me()
        bot_id = int(bot.get("id", 0))
        chat = self.api.get_chat(int(self.group_id))
        title = str(chat.get("title") or "").casefold()
        if (
            bot_id <= 0
            or int(chat.get("id", 0)) != DEFAULT_EDUCATION_GROUP_ID
            or chat.get("type") != "supergroup"
            or chat.get("is_forum") is not True
            or "pro signals" in title
            or re.search(r"\b(?:test|testing|sandbox)\b", title)
        ):
            raise ValueError("weekly_brief_destination_not_verified")
        member = self.api.get_chat_member(int(self.group_id), bot_id)
        status = member.get("status")
        if status not in {"creator", "administrator", "member"} or member.get(
            "can_send_messages"
        ) is False:
            raise ValueError("weekly_brief_posting_permission_missing")

    @staticmethod
    def _sources_checked_recently(
        statuses: list[dict], now_utc: datetime
    ) -> bool:
        by_name = {str(row.get("source_name")): row for row in statuses}
        if not _REQUIRED_SOURCES.issubset(by_name):
            return False
        for name in _REQUIRED_SOURCES:
            checked_at = _parse_utc(by_name[name].get("checked_at_utc"))
            if checked_at is None:
                return False
            age = now_utc - checked_at
            if age < timedelta(0) or age > SOURCE_REFRESH_REUSE_WINDOW:
                return False
        return True

    def _estimate_impacts(self, records: list[dict]) -> dict[str, str]:
        if self.impact_estimator is None or not records:
            return {}
        try:
            return self.impact_estimator.estimate(records)
        except Exception:
            logger.warning("Weekly brief impact estimate failed; keeping rating unavailable.")
            return {}

    def _notify_admin(self, message: str) -> None:
        if self.admin_id is None:
            return
        try:
            self.api.send_message(self.admin_id, message)
        except TelegramAPIError:
            logger.warning("Could not privately notify admin about weekly USD/Gold brief.")


__all__ = [
    "WEEKLY_BRIEF_GRACE",
    "WEEKLY_BRIEF_TIME",
    "WeeklyCalendarBriefPublisher",
    "WeeklyCalendarBriefStore",
    "build_weekly_usd_gold_brief",
]
