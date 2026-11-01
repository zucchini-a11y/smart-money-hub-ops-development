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
    MARKET_ANALYSIS_CHANNEL_ID,
    TELEGRAM_MESSAGE_LIMIT_UTF16,
)
from .economic_calendar_phase1 import (
    OfficialCalendarRepository,
    fetch_and_store_official_schedules,
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


def _escape_link(url: str, label: str) -> str:
    return (
        f'<a href="{html.escape(url, quote=True)}">'
        f"{html.escape(label)}</a>"
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


def _event_relevance(title: str) -> str:
    normalized = title.casefold()
    if any(term in normalized for term in ("cpi", "pce", "ppi", "inflation", "price index")):
        return (
            "Inflation data can affect policy expectations, USD and gold; "
            "the market response is not predetermined."
        )
    if any(
        term in normalized
        for term in (
            "employment",
            "payroll",
            "job openings",
            "jobless claims",
            "labor",
            "productivity",
        )
    ):
        return (
            "Labor conditions can influence policy expectations, USD and gold; "
            "the reaction may differ from the headline."
        )
    if any(
        term in normalized
        for term in (
            "fomc",
            "federal reserve",
            "interest rate",
            "personal income",
        )
    ):
        return (
            "Policy or spending information can shape USD and gold expectations; "
            "outcomes and reactions remain uncertain."
        )
    return (
        "Growth, demand, or trade information may affect the USD outlook and "
        "gold context; no direction is guaranteed."
    )


def build_weekly_usd_gold_brief(
    week_start: date,
    records: list[dict],
    source_status: list[dict],
    *,
    now: datetime,
) -> str:
    """Render fresh official records for Monday–Sunday without inferred fields."""
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

    events: list[tuple[date, datetime | None, dict]] = []
    eligible_sources = {
        "U.S. Bureau of Economic Analysis",
        "U.S. Bureau of Labor Statistics",
        "U.S. Census Bureau",
        "Federal Reserve",
    }
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
    lines = [
        "🌍 <b>VAYDA SMART MONEY HUB | WEEKLY USD &amp; GOLD BRIEF</b>",
        f"📅 Week of {week_start.strftime('%d %B %Y')} · WAT",
        "",
        "🇺🇸 <b>USD &amp; MACRO UPDATE</b>",
        "This is an official U.S. economic-release calendar. It contains "
        "scheduled events only; it does not claim live market prices or "
        "unverified breaking news.",
        "",
        "🥇 <b>GOLD IMPACT</b>",
        "Economic releases may influence growth and interest-rate expectations, "
        "which can affect USD and gold. Direction is uncertain and can differ "
        "from an initial interpretation.",
        "",
        "📅 <b>THIS WEEK’S U.S. RELEASES</b>",
    ]

    if not events:
        lines.extend(
            [
                "No fresh, verified entries from the configured official "
                "calendars were found for this week.",
                "",
            ]
        )
    for event_date, event_at, record in events:
        title = html.escape(str(record.get("title") or "Official U.S. release"))
        source = str(record.get("source_name") or "Official source")
        source_url = str(record.get("source_url") or "")
        label = {
            "U.S. Bureau of Economic Analysis": "BEA",
            "U.S. Bureau of Labor Statistics": "BLS",
            "U.S. Census Bureau": "U.S. Census Bureau",
            "Federal Reserve": "Federal Reserve",
        }.get(source, source)

        if source == "U.S. Census Bureau":
            timing = "Time: Unavailable in WAT; source timezone is not verified."
        elif source == "Federal Reserve":
            timing = "Meeting window; no decision release time is stated."
        elif event_at is not None:
            timing = (
                f"{event_at.astimezone(WAT).strftime('%H:%M WAT')} "
                "(converted from the source’s verified timezone)"
            )
        else:
            timing = "Time: Unavailable; source timezone is not verified."

        lines.extend(
            [
                f"• <b>{event_date.strftime('%a, %d %b')} — {title}</b>",
                timing,
                "Impact: Unavailable from the official schedule.",
                "Previous: "
                + html.escape(str(record.get("previous") or "Unavailable"))
                + " · Forecast: "
                + html.escape(str(record.get("forecast") or "Unavailable"))
                + " · Actual: "
                + html.escape(
                    str(record.get("actual") or "Unavailable from schedule source")
                ),
                f"Possible relevance: {_event_relevance(str(record.get('title') or ''))}",
                f"Source: {_escape_link(source_url, label)}",
                "",
            ]
        )

    source_checks = [
        (name, statuses.get(name, {}))
        for name in ("BEA", "BLS", "Census", "Federal Reserve", "DOL")
    ]
    checked_times = [
        parsed
        for _, status in source_checks
        if (parsed := _parse_utc(status.get("checked_at_utc"))) is not None
        and timedelta(0) <= now_utc - parsed <= CALENDAR_STALE_AFTER
    ]
    checked_label = (
        max(checked_times).astimezone(WAT).strftime("%a, %d %b at %H:%M WAT")
        if checked_times
        else "not available"
    )
    unverified = [
        name
        for name, status in source_checks
        if not (
            status.get("status") == "verified_schedule"
            and _fresh_timestamp(status.get("checked_at_utc"), now_utc)
        )
    ]
    status_parts = []
    if unverified:
        status_parts.append(
            f"{', '.join(unverified)} schedule coverage is unavailable or not verified."
        )
    if source_verified("Census"):
        status_parts.append(
            "Census times are not converted or used for reminders because its "
            "source timezone is not verified."
        )
    status_parts.append(
        "Missing figures and impact classifications are not inferred."
    )

    lines.extend(
        [
            "🎯 <b>WHAT TRADERS SHOULD WATCH</b>",
            "Check verified results when released and observe the market response. "
            "A scheduled event is not an entry signal.",
            "",
            "⚠️ <b>NO CONFIRMATION, NO ENTRY.</b>",
            "📌 <b>SOURCE STATUS</b>",
            f"Official calendars checked: {checked_label}.",
            " ".join(status_parts),
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
        channel_id: int | None,
        source_refresh=fetch_and_store_official_schedules,
    ) -> None:
        self.api = api
        self.database_path = Path(database_path)
        self.admin_id = admin_id
        self.channel_id = channel_id
        self.calendar = OfficialCalendarRepository(database_path)
        self.store = WeeklyCalendarBriefStore(database_path)
        self.source_refresh = source_refresh

    def dispatch(self, now: datetime | None = None) -> str:
        current = _utc(now or datetime.now(timezone.utc))
        local_now = current.astimezone(WAT)
        if local_now.weekday() != 0:
            return "not_due"
        if local_now.time().replace(tzinfo=None) < WEEKLY_BRIEF_TIME:
            return "not_due"
        if self.admin_id is None or self.channel_id is None:
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
                    "interrupted send. Check Market Analysis before any retry.",
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

            report = build_weekly_usd_gold_brief(
                week_start,
                self.calendar.list_records(),
                statuses,
                now=current,
            )
            self._verify_destination()
            result = self.api.send_message_with_result(
                int(self.channel_id), report, parse_mode="HTML"
            )
            message_id = result.get("message_id") if isinstance(result, dict) else None
            if not isinstance(message_id, int) or message_id <= 0:
                raise TelegramAPIError(
                    "Telegram did not confirm the weekly message.",
                    delivery_unknown=True,
                )
            self.store.finish(
                week_start,
                status="published",
                now=datetime.now(timezone.utc),
                content=report,
                message_id=message_id,
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
        if int(self.channel_id or 0) != MARKET_ANALYSIS_CHANNEL_ID:
            raise ValueError("weekly_brief_destination_mismatch")
        bot = self.api.get_me()
        bot_id = int(bot.get("id", 0))
        chat = self.api.get_chat(int(self.channel_id))
        title = str(chat.get("title") or "").casefold()
        if (
            bot_id <= 0
            or int(chat.get("id", 0)) != MARKET_ANALYSIS_CHANNEL_ID
            or chat.get("type") != "channel"
            or "pro signals" in title
            or re.search(r"\b(?:test|testing|sandbox)\b", title)
        ):
            raise ValueError("weekly_brief_destination_not_verified")
        member = self.api.get_chat_member(int(self.channel_id), bot_id)
        status = member.get("status")
        if not (
            status == "creator"
            or (status == "administrator" and member.get("can_post_messages") is True)
        ):
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
