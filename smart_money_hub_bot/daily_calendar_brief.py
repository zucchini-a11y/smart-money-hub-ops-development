"""Safe daily USD/Gold calendar brief publishing to Market Analysis."""

from __future__ import annotations

import hashlib
import html
import logging
import sqlite3
import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .economic_calendar_phase1 import (
    CALENDAR_STALE_AFTER,
    OfficialCalendarRepository,
    fetch_and_store_official_schedules,
)
from .telegram_api import TelegramAPI, TelegramAPIError

logger = logging.getLogger(__name__)

WAT = ZoneInfo("Africa/Lagos")
DAILY_BRIEF_TIME = datetime.strptime("00:00", "%H:%M").time()
DAILY_BRIEF_GRACE = timedelta(minutes=15)
MARKET_ANALYSIS_CHANNEL_ID = -1004481197912
TELEGRAM_MESSAGE_LIMIT_UTF16 = 4096
_ALLOWED_SOURCE_HOSTS = {"bea.gov", "www.bea.gov", "apps.bea.gov"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Calendar timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed) if parsed.tzinfo else None


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _safe_bea_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_SOURCE_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def build_daily_usd_gold_brief(
    brief_date: date,
    records: list[dict],
    source_status: list[dict],
    *,
    now: datetime | None = None,
) -> str:
    """Render only fresh, offset-verified BEA events for one WAT date."""
    observed = _as_utc(now or datetime.now(timezone.utc))
    statuses = {str(row.get("source_name")): row for row in source_status}
    verified_events: list[tuple[datetime, dict]] = []
    for record in records:
        if record.get("source_name") != "U.S. Bureau of Economic Analysis":
            continue
        if record.get("verification_status") != "verified_schedule":
            continue
        retrieved_at = _parse_utc(record.get("retrieved_at_utc"))
        event_at = _parse_utc(record.get("event_at_utc"))
        if retrieved_at is None or event_at is None:
            continue
        age = observed - retrieved_at
        if age < timedelta(0) or age > CALENDAR_STALE_AFTER:
            continue
        if event_at.astimezone(WAT).date() != brief_date:
            continue
        if not _safe_bea_url(record.get("source_url")):
            continue
        verified_events.append((event_at, record))

    verified_events.sort(key=lambda item: item[0])
    lines = [
        "🌍 <b>VAYDA SMART MONEY HUB | DAILY USD &amp; GOLD BRIEF</b>",
        f"📅 {brief_date.strftime('%A, %d %B %Y')} · 12:00 AM WAT",
        "",
        "🇺🇸 <b>VERIFIED U.S. RELEASES</b>",
    ]
    if not verified_events:
        lines.extend(["No verified BEA releases are listed for this WAT date.", ""])
    for event_at, record in verified_events:
        title = html.escape(str(record.get("title") or "Official BEA release"))
        url = html.escape(str(record["source_url"]), quote=True)
        lines.extend(
            [
                f"⏰ <b>{event_at.astimezone(WAT).strftime('%H:%M WAT')} — {title}</b>",
                "Provider impact: Unavailable",
                "Previous: Unavailable · Forecast: Unavailable",
                "Actual: Unavailable from this schedule source",
                f'Source: <a href="{url}">U.S. Bureau of Economic Analysis</a>',
                "",
            ]
        )
        if "personal income and outlays" in str(record.get("title", "")).casefold():
            lines.append(
                "Possible relevance: This release includes PCE data; inflation and "
                "household-spending information may affect rate expectations."
            )
        elif "gross domestic product" in str(record.get("title", "")).casefold():
            lines.append(
                "Possible relevance: GDP informs the U.S. growth outlook and may "
                "affect rate expectations."
            )
        else:
            lines.append(
                "Possible relevance: The release may affect USD and gold through "
                "economic and rate expectations."
            )
        lines.append(
            "Any market reaction is uncertain and depends on the result and wider context."
        )
        lines.append("")

    census = statuses.get("Census", {})
    if census.get("status") == "verified_schedule":
        census_note = (
            "Census dates are recorded, but its timezone is not verified; "
            "no WAT time or reminder is inferred."
        )
    else:
        census_note = "Census coverage is unavailable or not verified."
    unavailable = []
    for name in ("BLS", "DOL"):
        status = statuses.get(name, {})
        if status.get("status") != "verified_schedule":
            code = status.get("http_status")
            suffix = f" (HTTP {int(code)})" if isinstance(code, int) else ""
            unavailable.append(f"{name} unavailable{suffix}")
    coverage = "; ".join(unavailable) if unavailable else "BLS and DOL source status verified"
    lines.extend(
        [
            "🥇 <b>GOLD WATCH</b>",
            "News is context, not an entry signal. Consider the dollar, yields, "
            "expectations, and technical confirmation; direction is not guaranteed.",
            "",
            "📌 <b>SOURCE COVERAGE</b>",
            f"{census_note} {html.escape(coverage)}. Missing figures and impact levels are not inferred.",
            "",
            "⚠️ <b>NO CONFIRMATION, NO ENTRY.</b>",
            "Sources: official U.S. release schedules. No live prices or trade signals.",
        ]
    )
    report = "\n".join(lines)
    if _utf16_length(report) > TELEGRAM_MESSAGE_LIMIT_UTF16:
        raise ValueError("daily_brief_exceeds_telegram_limit")
    return report


class DailyCalendarBriefStore:
    """Persistent, at-most-once delivery state, keyed by WAT calendar date."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS usd_gold_daily_brief_runs (
                        brief_date TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 1,
                        content_sha256 TEXT,
                        review_content TEXT,
                        telegram_message_id INTEGER,
                        failure_category TEXT,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    )
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(usd_gold_daily_brief_runs)"
                    ).fetchall()
                }
                if "review_content" not in columns:
                    connection.execute(
                        "ALTER TABLE usd_gold_daily_brief_runs "
                        "ADD COLUMN review_content TEXT"
                    )

    def reserve(self, brief_date: date, now: datetime) -> tuple[bool, str | None]:
        observed = _as_utc(now).isoformat(timespec="seconds")
        connection = sqlite3.connect(self.database_path)
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT status FROM usd_gold_daily_brief_runs WHERE brief_date=?",
                    (brief_date.isoformat(),),
                ).fetchone()
                if row:
                    return False, str(row[0])
                connection.execute(
                    """
                    INSERT INTO usd_gold_daily_brief_runs
                        (brief_date,status,attempts,created_at_utc,updated_at_utc)
                    VALUES (?,'sending',1,?,?)
                    """,
                    (brief_date.isoformat(), observed, observed),
                )
                return True, None
        finally:
            connection.close()

    def finish(
        self,
        brief_date: date,
        *,
        status: str,
        now: datetime,
        content: str | None = None,
        message_id: int | None = None,
        failure_category: str | None = None,
    ) -> None:
        if status not in {
            "published",
            "held",
            "delivery_unknown",
            "skipped",
            "awaiting_approval",
        }:
            raise ValueError("Invalid daily brief delivery status.")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE usd_gold_daily_brief_runs
                    SET status=?, content_sha256=COALESCE(?, content_sha256),
                        telegram_message_id=COALESCE(?, telegram_message_id),
                        failure_category=?, updated_at_utc=?
                    WHERE brief_date=?
                    """,
                    (
                        status,
                        content_hash,
                        message_id,
                        failure_category,
                        _as_utc(now).isoformat(timespec="seconds"),
                        brief_date.isoformat(),
                    ),
                )

    def get(self, brief_date: date) -> dict | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM usd_gold_daily_brief_runs WHERE brief_date=?",
                (brief_date.isoformat(),),
            ).fetchone()
            return dict(row) if row else None

    def save_review(
        self, brief_date: date, content: str, *, now: datetime
    ) -> bool:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE usd_gold_daily_brief_runs
                    SET status='awaiting_approval', review_content=?,
                        content_sha256=?, failure_category=NULL, updated_at_utc=?
                    WHERE brief_date=? AND status IN ('held','awaiting_approval')
                      AND telegram_message_id IS NULL
                    """,
                    (
                        content,
                        content_hash,
                        _as_utc(now).isoformat(timespec="seconds"),
                        brief_date.isoformat(),
                    ),
                )
                return cursor.rowcount == 1

    def cancel_review(self, brief_date: date, *, now: datetime) -> bool:
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE usd_gold_daily_brief_runs
                    SET status='held', review_content=NULL, content_sha256=NULL,
                        failure_category='admin_cancelled_retry', updated_at_utc=?
                    WHERE brief_date=? AND status='awaiting_approval'
                      AND telegram_message_id IS NULL
                    """,
                    (
                        _as_utc(now).isoformat(timespec="seconds"),
                        brief_date.isoformat(),
                    ),
                )
                return cursor.rowcount == 1

    def claim_reviewed_send(
        self, brief_date: date, content: str, *, now: datetime
    ) -> bool:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE usd_gold_daily_brief_runs
                    SET status='sending', attempts=attempts+1, updated_at_utc=?
                    WHERE brief_date=? AND status='awaiting_approval'
                      AND content_sha256=? AND telegram_message_id IS NULL
                    """,
                    (
                        _as_utc(now).isoformat(timespec="seconds"),
                        brief_date.isoformat(),
                        content_hash,
                    ),
                )
                return cursor.rowcount == 1


class DailyCalendarBriefPublisher:
    """Refresh official records and publish one verified brief per WAT date."""

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
        self.store = DailyCalendarBriefStore(database_path)
        self.source_refresh = source_refresh

    def dispatch(self, now: datetime | None = None) -> str:
        current = _as_utc(now or datetime.now(timezone.utc))
        local_now = current.astimezone(WAT)
        if local_now.time().replace(tzinfo=None) < DAILY_BRIEF_TIME:
            return "not_due"
        if self.admin_id is None or self.channel_id is None:
            logger.error("Daily USD/Gold brief held: required destination configuration missing.")
            return "disabled"
        reserved, prior_status = self.store.reserve(local_now.date(), current)
        if not reserved:
            if prior_status == "sending":
                self.store.finish(
                    local_now.date(),
                    status="delivery_unknown",
                    now=current,
                    failure_category="interrupted_send_state",
                )
                self._notify_admin(
                    local_now.date(), "delivery_unknown",
                    "A prior send was interrupted; the bot will not resend automatically.",
                )
                return "delivery_unknown"
            return f"already_{prior_status}"
        scheduled_at = datetime.combine(
            local_now.date(), DAILY_BRIEF_TIME, tzinfo=WAT
        )
        if current > scheduled_at.astimezone(timezone.utc) + DAILY_BRIEF_GRACE:
            self.store.finish(
                local_now.date(),
                status="skipped",
                now=current,
                failure_category="missed_publication_window",
            )
            logger.warning(
                "Daily USD/Gold brief skipped after its WAT publication window "
                "(date=%s, no_channel_send=true).",
                local_now.date().isoformat(),
            )
            return "skipped_late"

        try:
            self.source_refresh(self.database_path, now=current)
            statuses = self.calendar.list_source_status()
            bea = next((row for row in statuses if row.get("source_name") == "BEA"), None)
            checked_at = _parse_utc(bea.get("checked_at_utc")) if bea else None
            source_age = current - checked_at if checked_at else None
            if (
                not bea
                or bea.get("status") != "verified_schedule"
                or source_age is None
                or source_age < timedelta(0)
                or source_age > CALENDAR_STALE_AFTER
            ):
                category = (
                    str(bea.get("failure_category") or "bea_source_not_verified")
                    if bea
                    else "bea_source_not_verified"
                )
                self.store.finish(
                    local_now.date(), status="held", now=current,
                    failure_category=category,
                )
                self._notify_admin(
                    local_now.date(), category,
                    "No channel post was sent because the BEA release schedule could not be verified as fresh.",
                )
                return "held_source_unverified"

            report = build_daily_usd_gold_brief(
                local_now.date(),
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
                    "Telegram did not confirm the channel message.",
                    delivery_unknown=True,
                )
            self.store.finish(
                local_now.date(),
                status="published",
                now=datetime.now(timezone.utc),
                content=report,
                message_id=message_id,
            )
            logger.info(
                "Daily USD/Gold brief published (date=%s, route=official_calendar, "
                "message_confirmed=true).",
                local_now.date().isoformat(),
            )
            incomplete = [
                row for row in statuses
                if row.get("source_name") in {"Census", "BLS", "DOL"}
                and row.get("status") != "verified_schedule"
            ]
            if incomplete:
                self._notify_admin(
                    local_now.date(),
                    "partial_source_coverage",
                    "The daily brief was published with its source-coverage note. "
                    "Some sources remain unavailable or unverified.",
                )
            return "published"
        except TelegramAPIError as error:
            status = "delivery_unknown" if error.delivery_unknown else "held"
            category = (
                "telegram_delivery_unknown"
                if error.delivery_unknown
                else f"telegram_http_{error.http_status}"
                if error.http_status
                else "telegram_send_failed"
            )
            self.store.finish(
                local_now.date(), status=status, now=current,
                failure_category=category,
            )
            self._notify_admin(
                local_now.date(), category,
                "The daily brief was not confirmed as published. Automatic resend is disabled to prevent duplicates.",
            )
            return status
        except (ValueError, OSError, sqlite3.Error) as error:
            category = (
                str(error) if str(error) == "daily_brief_exceeds_telegram_limit"
                else "daily_brief_preparation_failed"
            )
            self.store.finish(
                local_now.date(), status="held", now=current,
                failure_category=category,
            )
            self._notify_admin(
                local_now.date(), category,
                "The daily brief was held during preparation or destination verification. No channel post was sent.",
            )
            return "held"
        except Exception:
            self.store.finish(
                local_now.date(), status="held", now=current,
                failure_category="unexpected_daily_brief_error",
            )
            self._notify_admin(
                local_now.date(), "unexpected_daily_brief_error",
                "The daily brief was held because an unexpected error occurred. No automatic resend will occur.",
            )
            logger.exception("Daily USD/Gold brief dispatch failed safely.")
            return "held"

    def _verify_destination(self) -> None:
        if int(self.channel_id or 0) != MARKET_ANALYSIS_CHANNEL_ID:
            raise ValueError("daily_brief_destination_mismatch")
        bot = self.api.get_me()
        bot_id = int(bot.get("id", 0))
        if bot_id <= 0:
            raise ValueError("daily_brief_bot_identity_unavailable")
        chat = self.api.get_chat(int(self.channel_id))
        title = str(chat.get("title") or "").casefold()
        unsafe = "pro signals" in title or bool(
            re.search(r"\b(?:test|testing|sandbox)\b", title)
        )
        if int(chat.get("id", 0)) != MARKET_ANALYSIS_CHANNEL_ID or chat.get("type") != "channel" or unsafe:
            raise ValueError("daily_brief_destination_not_verified")
        member = self.api.get_chat_member(int(self.channel_id), bot_id)
        status = member.get("status")
        can_post = status == "creator" or (
            status == "administrator" and member.get("can_post_messages") is True
        )
        if not can_post:
            raise ValueError("daily_brief_posting_permission_missing")

    def prepare_held_review(
        self, *, now: datetime | None = None
    ) -> tuple[str, str | None]:
        """Prepare a private preview for today's held brief; never publish here."""
        current = _as_utc(now or datetime.now(timezone.utc))
        brief_date = current.astimezone(WAT).date()
        if self.admin_id is None or self.channel_id is None:
            return "disabled", None
        run = self.store.get(brief_date)
        if run is None:
            return "not_found", None
        if run.get("status") not in {"held", "awaiting_approval"}:
            return f"not_recoverable:{run.get('status')}", None

        try:
            report = self._prepare_verified_report(brief_date, current)
            preview = self._review_preview(brief_date, report)
            if _utf16_length(preview) > TELEGRAM_MESSAGE_LIMIT_UTF16:
                raise ValueError("daily_brief_review_exceeds_telegram_limit")
            if not self.store.save_review(brief_date, report, now=current):
                return "status_changed", None
            self._send_review_preview(brief_date, preview)
        except (TelegramAPIError, OSError, sqlite3.Error) as error:
            category = (
                str(error)
                if str(error) == "daily_brief_review_exceeds_telegram_limit"
                else "daily_brief_review_delivery_failed"
                if isinstance(error, TelegramAPIError)
                else "daily_brief_preparation_failed"
            )
            self._notify_admin(
                brief_date,
                category,
                "The held brief remains unpublished. Review preparation or delivery failed.",
            )
            return category, None
        except ValueError as error:
            category = str(error)
            self.store.finish(
                brief_date,
                status="held",
                now=current,
                failure_category=category,
            )
            self._notify_admin(
                brief_date,
                category,
                "The held brief remains unpublished because a required source or destination check failed.",
            )
            return category, None
        except Exception:
            self.store.finish(
                brief_date,
                status="held",
                now=current,
                failure_category="daily_brief_preparation_failed",
            )
            self._notify_admin(
                brief_date,
                "daily_brief_preparation_failed",
                "The held brief remains unpublished after a preparation error.",
            )
            logger.exception("Held daily brief review preparation failed safely.")
            return "daily_brief_preparation_failed", None
        return "awaiting_approval", preview

    def publish_reviewed(
        self, brief_date: date, *, now: datetime | None = None
    ) -> str:
        """Publish only after an admin preview; recheck sources and destination."""
        current = _as_utc(now or datetime.now(timezone.utc))
        if current.astimezone(WAT).date() != brief_date:
            return "not_current_date"
        run = self.store.get(brief_date)
        if not run or run.get("status") != "awaiting_approval":
            return "not_awaiting_approval"
        saved_content = run.get("review_content")
        if not isinstance(saved_content, str) or not saved_content:
            return "review_content_missing"

        try:
            report = self._prepare_verified_report(brief_date, current)
        except (TelegramAPIError, ValueError, OSError, sqlite3.Error) as error:
            category = str(error) if isinstance(error, ValueError) else (
                "destination_verification_unavailable"
                if isinstance(error, TelegramAPIError)
                else "daily_brief_preparation_failed"
            )
            self.store.finish(
                brief_date,
                status="held",
                now=current,
                failure_category=category,
            )
            self._notify_admin(
                brief_date,
                category,
                "The brief was not published because a current source or destination check failed.",
            )
            return "held"

        if report != saved_content:
            preview = self._review_preview(brief_date, report)
            if _utf16_length(preview) > TELEGRAM_MESSAGE_LIMIT_UTF16:
                self.store.finish(
                    brief_date,
                    status="held",
                    now=current,
                    failure_category="daily_brief_review_exceeds_telegram_limit",
                )
                return "review_too_long"
            if not self.store.save_review(brief_date, report, now=current):
                return "status_changed"
            try:
                self._send_review_preview(brief_date, preview)
            except TelegramAPIError:
                self._notify_admin(
                    brief_date,
                    "daily_brief_review_delivery_failed",
                    "The refreshed preview could not be delivered. The brief remains unpublished.",
                )
                return "preview_delivery_failed"
            return "preview_updated"

        if not self.store.claim_reviewed_send(brief_date, report, now=current):
            return "status_changed"
        try:
            result = self.api.send_message_with_result(
                int(self.channel_id), report, parse_mode="HTML"
            )
            message_id = result.get("message_id") if isinstance(result, dict) else None
            if not isinstance(message_id, int) or message_id <= 0:
                raise TelegramAPIError(
                    "Telegram did not confirm the channel message.",
                    delivery_unknown=True,
                )
            self.store.finish(
                brief_date,
                status="published",
                now=datetime.now(timezone.utc),
                content=report,
                message_id=message_id,
            )
            logger.info(
                "Held daily USD/Gold brief published after admin approval "
                "(date=%s, message_confirmed=true).",
                brief_date.isoformat(),
            )
            return "published"
        except TelegramAPIError as error:
            status = "delivery_unknown" if error.delivery_unknown else "held"
            category = (
                "telegram_delivery_unknown"
                if error.delivery_unknown
                else f"telegram_http_{error.http_status}"
                if error.http_status
                else "telegram_send_failed"
            )
            self.store.finish(
                brief_date,
                status=status,
                now=current,
                failure_category=category,
            )
            self._notify_admin(
                brief_date,
                category,
                "The approved brief was not confirmed as published. It will not be resent automatically.",
            )
            return status
        except Exception:
            self.store.finish(
                brief_date,
                status="delivery_unknown",
                now=current,
                failure_category="telegram_delivery_unknown",
            )
            self._notify_admin(
                brief_date,
                "telegram_delivery_unknown",
                "The approved brief's delivery could not be confirmed. Automatic resend is disabled.",
            )
            logger.exception("Approved held daily brief send outcome is uncertain.")
            return "delivery_unknown"

    def cancel_review(self, brief_date: date, *, now: datetime | None = None) -> bool:
        return self.store.cancel_review(
            brief_date,
            now=_as_utc(now or datetime.now(timezone.utc)),
        )

    def _prepare_verified_report(self, brief_date: date, current: datetime) -> str:
        self.source_refresh(self.database_path, now=current)
        statuses = self.calendar.list_source_status()
        bea = next((row for row in statuses if row.get("source_name") == "BEA"), None)
        checked_at = _parse_utc(bea.get("checked_at_utc")) if bea else None
        source_age = current - checked_at if checked_at else None
        if (
            not bea
            or bea.get("status") != "verified_schedule"
            or source_age is None
            or source_age < timedelta(0)
            or source_age > CALENDAR_STALE_AFTER
        ):
            raise ValueError(
                str(bea.get("failure_category") or "bea_source_not_verified")
                if bea
                else "bea_source_not_verified"
            )
        report = build_daily_usd_gold_brief(
            brief_date,
            self.calendar.list_records(),
            statuses,
            now=current,
        )
        self._verify_destination()
        return report

    def _review_preview(self, brief_date: date, report: str) -> str:
        return (
            "<b>HELD DAILY BRIEF — ADMIN REVIEW</b>\n"
            "Not published. Approve below to publish once.\n"
            f"Destination: Market Analysis (ID {MARKET_ANALYSIS_CHANNEL_ID})\n"
            f"Scheduled date: {brief_date.isoformat()} at 00:00 WAT\n\n"
            f"{report}"
        )

    def _send_review_preview(self, brief_date: date, preview: str) -> None:
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "Publish Now",
                        "callback_data": f"dailybrief:publish:{brief_date.isoformat()}",
                    },
                    {
                        "text": "Cancel",
                        "callback_data": f"dailybrief:cancel:{brief_date.isoformat()}",
                    },
                ]
            ]
        }
        self.api.send_message(
            int(self.admin_id),
            preview,
            keyboard,
            parse_mode="HTML",
        )

    def _notify_admin(self, brief_date: date, category: str, explanation: str) -> None:
        if self.admin_id is None:
            logger.warning(
                "Daily USD/Gold brief admin notice unavailable (date=%s, category=%s).",
                brief_date.isoformat(),
                category,
            )
            return
        try:
            self.api.send_message(
                int(self.admin_id),
                f"Daily USD & Gold brief — {brief_date.isoformat()}\n"
                f"Status: {category}\n{explanation}",
            )
        except Exception:
            logger.warning(
                "Could not deliver daily brief admin notice (date=%s, category=%s).",
                brief_date.isoformat(),
                category,
            )
