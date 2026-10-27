"""Phase-one, official-source-only USD/XAU release-calendar ingestion.

This module records source material for review. It does not publish to Telegram
and is not wired into the bot scheduler until the destination and sample report
are approved.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import calendar
import re
import socket
import sqlite3
import time
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .news_intelligence import NewsRepository, NewsSourceError

logger = logging.getLogger(__name__)

BEA_RELEASE_DATES_URL = "https://apps.bea.gov/API/signup/release_dates.json"
FED_FOMC_CALENDAR_URL = (
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
)
CENSUS_RELEASE_CALENDAR_URL = (
    "https://www.census.gov/economic-indicators/calendar-listview.html"
)
BLS_RELEASE_SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
DOL_CLAIMS_SCHEDULE_URL = "https://www.dol.gov/agencies/eta/ui/claims"

_ALLOWED_HOSTS = frozenset(
    {
        "apps.bea.gov",
        "www.bea.gov",
        "www.census.gov",
        "www.bls.gov",
        "www.dol.gov",
        "www.federalreserve.gov",
    }
)
_WAT = ZoneInfo("Africa/Lagos")
_MAX_BODY_BYTES = 4_000_000
CALENDAR_STALE_AFTER = timedelta(hours=24)
CALENDAR_REVIEW_PAGE_SIZE = 2
_TRANSIENT_FAILURES = {
    "rate_limit",
    "service_unavailable",
    "timeout",
    "network_error",
}


@dataclass(frozen=True)
class OfficialCalendarRecord:
    external_id: str
    source_name: str
    affected_instrument: str
    title: str
    source_url: str
    retrieved_at: datetime
    release_date_text: str
    release_time_text: str | None
    event_at_utc: datetime | None
    timezone_status: str
    previous: str | None = None
    forecast: str | None = None
    actual: str | None = None
    provider_impact: str | None = None
    verification_status: str = "verified_schedule"

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("Retrieval timestamps must be timezone-aware.")
        if self.event_at_utc is not None and self.event_at_utc.tzinfo is None:
            raise ValueError("Calendar event timestamps must be timezone-aware.")

    @property
    def event_at_wat(self) -> datetime | None:
        if self.event_at_utc is None:
            return None
        return self.event_at_utc.astimezone(_WAT)


def _event_id(source: str, title: str, schedule: str) -> str:
    canonical = "|".join((source.casefold(), title.casefold(), schedule))
    return f"{source.casefold()}:{hashlib.sha256(canonical.encode()).hexdigest()[:24]}"


def _safe_source_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def _fetch_bytes(
    url: str,
    *,
    opener=urlopen,
    timeout: float = 8,
) -> tuple[bytes, int]:
    if not _safe_source_url(url):
        raise NewsSourceError("source_url_not_allowlisted")
    request = Request(
        url,
        headers={
            "Accept": "application/json, text/html, text/calendar",
            "User-Agent": "SmartMoneyHubOfficialCalendar/1.0",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read(_MAX_BODY_BYTES + 1)
            status = int(getattr(response, "status", 200))
    except HTTPError as error:
        category = {
            401: "authentication_error",
            403: "permission_error",
            404: "not_found",
            429: "rate_limit",
            503: "service_unavailable",
        }.get(int(error.code), "http_error")
        raise NewsSourceError(category, int(error.code)) from None
    except (TimeoutError, socket.timeout):
        raise NewsSourceError("timeout") from None
    except URLError as error:
        reason = error.reason
        category = (
            "timeout"
            if isinstance(reason, (TimeoutError, socket.timeout))
            or "timed out" in str(reason).casefold()
            else "network_error"
        )
        raise NewsSourceError(category) from None
    except OSError as error:
        category = (
            "timeout"
            if isinstance(error, (TimeoutError, socket.timeout))
            or "timed out" in str(error).casefold()
            else "network_error"
        )
        raise NewsSourceError(category) from None
    if len(body) > _MAX_BODY_BYTES:
        raise NewsSourceError("response_too_large", status)
    if not 200 <= status < 300:
        raise NewsSourceError("http_error", status)
    return body, status


def fetch_with_bounded_backoff(
    fetch,
    *,
    sleep=time.sleep,
    max_attempts: int = 3,
    initial_backoff_seconds: float = 1.0,
):
    """Retry transient source failures a bounded number of times only."""
    if max_attempts < 1 or max_attempts > 3:
        raise ValueError("max_attempts must be between 1 and 3.")
    for attempt in range(max_attempts):
        try:
            return fetch()
        except NewsSourceError as error:
            if error.category not in _TRANSIENT_FAILURES or attempt + 1 >= max_attempts:
                raise
            delay = min(initial_backoff_seconds * (2**attempt), 4.0)
            logger.warning(
                "Official calendar source retry scheduled (category=%s, "
                "http_status=%s, attempt=%s).",
                error.category,
                error.http_status or "unavailable",
                attempt + 2,
            )
            sleep(delay)
    raise AssertionError("Unreachable retry state.")


def parse_bea_release_dates(
    payload: dict,
    *,
    retrieved_at: datetime,
    start_at: datetime,
    end_at: datetime,
) -> list[OfficialCalendarRecord]:
    """Parse only the BEA GDP and Personal Income/Outlays schedule entries."""
    if any(value.tzinfo is None for value in (retrieved_at, start_at, end_at)):
        raise ValueError("Calendar range and retrieval time must be timezone-aware.")
    if not isinstance(payload, dict):
        raise NewsSourceError("malformed_bea_calendar")
    selected = {
        "Gross Domestic Product",
        "Personal Income and Outlays",
    }
    records: list[OfficialCalendarRecord] = []
    for title in selected:
        source_record = payload.get(title)
        dates = (
            source_record.get("release_dates")
            if isinstance(source_record, dict)
            else None
        )
        if not isinstance(dates, list):
            continue
        for raw_date in dates:
            if not isinstance(raw_date, str):
                continue
            try:
                event_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                continue
            if event_at.tzinfo is None:
                continue
            event_at = event_at.astimezone(timezone.utc)
            if not start_at.astimezone(timezone.utc) <= event_at <= end_at.astimezone(
                timezone.utc
            ):
                continue
            records.append(
                OfficialCalendarRecord(
                    # Keep the same event identity if the official source revises
                    # the release time on that date, so admin review can flag the
                    # changed source fingerprint instead of creating a duplicate.
                    external_id=_event_id(
                        "bea", title, event_at.date().isoformat()
                    ),
                    source_name="U.S. Bureau of Economic Analysis",
                    affected_instrument="USD / XAUUSD",
                    title=title,
                    source_url="https://www.bea.gov/news/schedule",
                    retrieved_at=retrieved_at,
                    release_date_text=event_at.astimezone(_WAT).strftime(
                        "%a, %d %b %Y"
                    ),
                    release_time_text=raw_date,
                    event_at_utc=event_at,
                    timezone_status="verified_explicit_utc_offset",
                )
            )
    return sorted(records, key=lambda record: record.event_at_utc or start_at)


class _CensusCalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_calendar = False
        self.in_row = False
        self.in_cell = False
        self.cells: list[dict[str, str]] = []
        self.current_cell: dict[str, str] | None = None
        self.rows: list[list[dict[str, str]]] = []
        self.current_href: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "calendar":
            self.in_calendar = True
        elif self.in_calendar and tag == "tr":
            self.in_row = True
            self.cells = []
        elif self.in_row and tag == "td":
            self.in_cell = True
            self.current_cell = {"text": ""}
        elif self.in_cell and tag == "a":
            self.current_href = attributes.get("href")
            if self.current_cell is not None and self.current_href:
                self.current_cell["href"] = self.current_href

    def handle_data(self, data: str) -> None:
        if self.in_cell and self.current_cell is not None:
            self.current_cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.current_href = None
        elif tag == "td" and self.in_cell and self.current_cell is not None:
            self.current_cell["text"] = " ".join(self.current_cell["text"].split())
            self.cells.append(self.current_cell)
            self.current_cell = None
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.cells:
                self.rows.append(self.cells)
            self.cells = []
            self.in_row = False
        elif tag == "table" and self.in_calendar:
            self.in_calendar = False


def parse_bls_release_ics(
    body: bytes,
    *,
    retrieved_at: datetime,
    start_at: datetime,
    end_at: datetime,
) -> list[OfficialCalendarRecord]:
    """Parse only official BLS CPI, PPI, and Employment Situation schedule items."""
    if any(value.tzinfo is None for value in (retrieved_at, start_at, end_at)):
        raise ValueError("Calendar range and retrieval time must be timezone-aware.")

    text = body.decode("utf-8", "replace")
    text = re.sub(r"\r?\n[ \t]", "", text)
    titles = (
        (("consumer price index",), "Consumer Price Index (CPI)"),
        (("producer price index",), "Producer Price Index (PPI)"),
        (("employment situation", "nonfarm payroll"), "Employment Situation"),
    )
    records: list[OfficialCalendarRecord] = []

    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        summary_match = re.search(r"^SUMMARY(?:;[^:]*)?:(.*)$", block, re.M)
        start_match = re.search(r"^DTSTART(?:;[^:]*)?:.*$", block, re.M)
        if not summary_match or not start_match:
            continue
        summary = summary_match.group(1).strip().casefold()
        title = next(
            (
                label
                for phrases, label in titles
                if any(phrase in summary for phrase in phrases)
            ),
            None,
        )
        if title is None:
            continue

        property_line = start_match.group(0)
        if ":" not in property_line:
            continue
        property_name, raw_value = property_line.split(":", 1)
        raw_value = raw_value.strip()
        try:
            source_date = datetime.strptime(raw_value[:8], "%Y%m%d").date()
        except ValueError:
            continue

        event_at_utc: datetime | None = None
        timezone_status = "unverified_missing_source_timezone"
        tzid_match = re.search(r"(?:^|;)TZID=(?:\"([^\"]+)\"|([^;:]+))", property_name)
        tzid = next((value for value in tzid_match.groups() if value), None) if tzid_match else None
        if re.fullmatch(r"\d{8}T\d{6}Z", raw_value):
            event_at_utc = datetime.strptime(raw_value, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            timezone_status = "verified_source_timezone:UTC"
        elif re.fullmatch(r"\d{8}T\d{6}", raw_value) and tzid:
            try:
                source_zone = ZoneInfo(tzid)
                source_time = datetime.strptime(
                    raw_value, "%Y%m%dT%H%M%S"
                ).replace(tzinfo=source_zone)
            except (ValueError, ZoneInfoNotFoundError):
                source_zone = None
            if source_zone is not None:
                event_at_utc = source_time.astimezone(timezone.utc)
                timezone_status = f"verified_source_timezone:{tzid}"
        elif re.fullmatch(r"\d{8}", raw_value):
            timezone_status = "date_only_no_time"

        if not start_at.date() <= source_date <= end_at.date():
            continue

        records.append(
            OfficialCalendarRecord(
                external_id=_event_id("bls", title, source_date.isoformat()),
                source_name="U.S. Bureau of Labor Statistics",
                affected_instrument="USD / XAUUSD",
                title=title,
                source_url=BLS_RELEASE_SCHEDULE_URL,
                retrieved_at=retrieved_at,
                release_date_text=source_date.isoformat(),
                release_time_text=property_line,
                event_at_utc=event_at_utc,
                timezone_status=timezone_status,
                verification_status="verified_schedule",
            )
        )

    return records


def parse_census_retail_calendar(
    body: bytes,
    *,
    retrieved_at: datetime,
) -> list[OfficialCalendarRecord]:
    """Parse Census retail release labels without assuming an unstated timezone."""
    if retrieved_at.tzinfo is None:
        raise ValueError("Retrieval time must be timezone-aware.")
    try:
        parser = _CensusCalendarParser()
        parser.feed(body.decode("utf-8", "replace"))
    except Exception:
        raise NewsSourceError("malformed_census_calendar") from None

    results: list[OfficialCalendarRecord] = []
    for cells in parser.rows:
        if len(cells) < 4:
            continue
        title = cells[0].get("text", "")
        if title.casefold() != "advance monthly sales for retail and food services":
            continue
        release_date = cells[1].get("text", "")
        release_time = cells[2].get("text", "")
        try:
            datetime.strptime(release_date, "%B %d, %Y")
        except ValueError:
            continue
        href = cells[0].get("href", "")
        source_url = urljoin("https://www.census.gov", href)
        if not _safe_source_url(source_url):
            source_url = CENSUS_RELEASE_CALENDAR_URL
        source_schedule = f"{release_date}|{release_time}"
        results.append(
            OfficialCalendarRecord(
                external_id=_event_id("census", title, source_schedule),
                source_name="U.S. Census Bureau",
                affected_instrument="USD / XAUUSD",
                title=title,
                source_url=source_url,
                retrieved_at=retrieved_at,
                release_date_text=release_date,
                release_time_text=release_time or None,
                event_at_utc=None,
                timezone_status="unverified_no_timezone_in_source",
                verification_status="date_time_listed_timezone_unverified",
            )
        )
    return results


class _FedMeetingCalendarParser(HTMLParser):
    """Extract only official FOMC meeting windows; not statement release times."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_year: int | None = None
        self.in_heading = False
        self.row_depth = 0
        self.div_classes: list[str] = []
        self.current_row: dict[str, str] | None = None
        self.rows: list[tuple[int, str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class", "")
        if tag == "h4":
            self.in_heading = True
        if tag != "div":
            return
        is_row = "fomc-meeting" in classes and "fomc-meeting__" not in classes
        if self.current_row is None and is_row:
            self.current_row = {"month": "", "date": ""}
            self.row_depth = 1
            self.div_classes = [classes]
        elif self.current_row is not None:
            self.row_depth += 1
            self.div_classes.append(classes)

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self.in_heading:
            match = re.search(r"\b(20\d{2})\s+FOMC Meetings\b", text)
            if match:
                self.current_year = int(match.group(1))
        if self.current_row is None or self.current_year is None:
            return
        for classes in reversed(self.div_classes):
            if "fomc-meeting__month" in classes:
                self.current_row["month"] += " " + text
                break
            if "fomc-meeting__date" in classes:
                self.current_row["date"] += " " + text
                break

    def handle_endtag(self, tag: str) -> None:
        if tag == "h4":
            self.in_heading = False
        elif tag == "div" and self.current_row is not None:
            if self.div_classes:
                self.div_classes.pop()
            self.row_depth -= 1
            if self.row_depth <= 0:
                month = " ".join(self.current_row["month"].split())
                meeting_dates = " ".join(self.current_row["date"].split())
                if month and meeting_dates and self.current_year:
                    self.rows.append((self.current_year, month, meeting_dates))
                self.current_row = None
                self.div_classes = []


def parse_fed_fomc_calendar(
    body: bytes,
    *,
    retrieved_at: datetime,
    start_at: datetime,
    end_at: datetime,
) -> list[OfficialCalendarRecord]:
    """Parse official meeting date ranges without inventing a decision time."""
    if any(value.tzinfo is None for value in (retrieved_at, start_at, end_at)):
        raise ValueError("Calendar range and retrieval time must be timezone-aware.")
    parser = _FedMeetingCalendarParser()
    try:
        parser.feed(body.decode("utf-8", "replace"))
    except Exception:
        raise NewsSourceError("malformed_fed_calendar") from None
    records: list[OfficialCalendarRecord] = []
    for year, month_name, meeting_range in parser.rows:
        try:
            month = list(calendar.month_name).index(month_name)
        except ValueError:
            continue
        match = re.search(r"(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*\*?", meeting_range)
        if not match:
            continue
        first_day = int(match.group(1))
        last_day = int(match.group(2) or match.group(1))
        try:
            range_start = datetime(year, month, first_day, tzinfo=timezone.utc)
            range_end = datetime(year, month, last_day, 23, 59, tzinfo=timezone.utc)
        except ValueError:
            continue
        if range_end < start_at.astimezone(timezone.utc) or range_start > end_at.astimezone(timezone.utc):
            continue
        label = (
            f"{month_name} {first_day}–{last_day}, {year}"
            if first_day != last_day
            else f"{month_name} {first_day}, {year}"
        )
        title = f"FOMC meeting window ({label})"
        records.append(
            OfficialCalendarRecord(
                external_id=_event_id("federal_reserve", title, label),
                source_name="Federal Reserve",
                affected_instrument="USD / XAUUSD",
                title=title,
                source_url=FED_FOMC_CALENDAR_URL,
                retrieved_at=retrieved_at,
                release_date_text=label,
                release_time_text=None,
                event_at_utc=None,
                timezone_status="meeting_window_no_release_time",
                verification_status="verified_meeting_window_release_time_unavailable",
            )
        )
    return records


class OfficialCalendarRepository:
    """Persistent source evidence/status; never sends Telegram messages."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS usd_calendar_source_status (
                    source_name TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    failure_category TEXT,
                    http_status INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    checked_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usd_calendar_source_events (
                    external_id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    release_date_text TEXT NOT NULL,
                    release_time_text TEXT,
                    event_at_utc TEXT,
                    affected_instrument TEXT NOT NULL DEFAULT 'USD / XAUUSD',
                    timezone_status TEXT NOT NULL,
                    previous_value TEXT,
                    forecast_value TEXT,
                    actual_value TEXT,
                    provider_impact TEXT,
                    verification_status TEXT NOT NULL,
                    retrieved_at_utc TEXT NOT NULL
                );
                """
            )
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(usd_calendar_source_events)"
                ).fetchall()
            }
            if "affected_instrument" not in columns:
                connection.execute(
                    "ALTER TABLE usd_calendar_source_events ADD COLUMN "
                    "affected_instrument TEXT NOT NULL DEFAULT 'USD / XAUUSD'"
                )

    def record_source_status(
        self,
        source_name: str,
        *,
        status: str,
        checked_at: datetime,
        failure_category: str | None = None,
        http_status: int | None = None,
        attempts: int = 1,
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                INSERT INTO usd_calendar_source_status
                    (source_name, status, failure_category, http_status, attempts,
                     checked_at_utc)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    status=excluded.status,
                    failure_category=excluded.failure_category,
                    http_status=excluded.http_status,
                    attempts=excluded.attempts,
                    checked_at_utc=excluded.checked_at_utc
                """,
                (
                    source_name,
                    status,
                    failure_category,
                    http_status,
                    attempts,
                    checked_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
                ),
            )

    def save_records(self, records: list[OfficialCalendarRecord]) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            for record in records:
                event_at = (
                    record.event_at_utc.astimezone(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    if record.event_at_utc
                    else None
                )
                connection.execute(
                    """
                    INSERT INTO usd_calendar_source_events (
                        external_id, source_name, title, source_url,
                        release_date_text, release_time_text, event_at_utc,
                        affected_instrument, timezone_status, previous_value, forecast_value,
                        actual_value, provider_impact, verification_status,
                        retrieved_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(external_id) DO UPDATE SET
                        source_url=excluded.source_url,
                        release_date_text=excluded.release_date_text,
                        release_time_text=excluded.release_time_text,
                        event_at_utc=excluded.event_at_utc,
                        affected_instrument=excluded.affected_instrument,
                        timezone_status=excluded.timezone_status,
                        previous_value=excluded.previous_value,
                        forecast_value=excluded.forecast_value,
                        actual_value=excluded.actual_value,
                        provider_impact=excluded.provider_impact,
                        verification_status=excluded.verification_status,
                        retrieved_at_utc=excluded.retrieved_at_utc
                    """,
                    (
                        record.external_id,
                        record.source_name,
                        record.title,
                        record.source_url,
                        record.release_date_text,
                        record.release_time_text,
                        event_at,
                        record.affected_instrument,
                        record.timezone_status,
                        record.previous,
                        record.forecast,
                        record.actual,
                        record.provider_impact,
                        record.verification_status,
                        record.retrieved_at.astimezone(timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                    ),
                )

    def list_records(self) -> list[dict]:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM usd_calendar_source_events "
                    "ORDER BY release_date_text, release_time_text"
                ).fetchall()
            ]

    def list_source_status(self) -> list[dict]:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM usd_calendar_source_status ORDER BY source_name"
                ).fetchall()
            ]


class OfficialCalendarReadRepository:
    """Read-only view of calendar tables; it never creates or migrates tables."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _read_table(self, table: str, order_by: str) -> list[dict]:
        if table not in {
            "usd_calendar_source_events",
            "usd_calendar_source_status",
        }:
            raise ValueError("Unsupported calendar review table.")
        if not self.database_path.exists():
            return []
        uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection, connection:
                connection.row_factory = sqlite3.Row
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if not exists:
                    return []
                return [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT * FROM {table} ORDER BY {order_by}"
                    ).fetchall()
                ]
        except sqlite3.Error:
            logger.warning("Calendar review read failed; displaying no records.")
            return []

    def list_records(self) -> list[dict]:
        return self._read_table(
            "usd_calendar_source_events",
            "release_date_text, release_time_text, external_id",
        )

    def list_source_status(self) -> list[dict]:
        return self._read_table("usd_calendar_source_status", "source_name")


def format_calendar_admin_review(
    records: list[dict],
    source_status: list[dict],
    *,
    page: int = 0,
    page_size: int = CALENDAR_REVIEW_PAGE_SIZE,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Format a private, read-only source review page as Telegram HTML."""
    if page_size < 1:
        raise ValueError("page_size must be positive.")
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    page_count = max(1, (len(records) + page_size - 1) // page_size)
    page = min(max(page, 0), page_count - 1)
    start = page * page_size
    selected = records[start : start + page_size]
    shown_start = start + 1 if records else 0
    shown_end = min(start + page_size, len(records))
    lines = [
        "<b>USD &amp; GOLD — ADMIN SOURCE REVIEW</b>",
        "Read-only records. This view is not connected to scheduling or publishing.",
        "Admin approval is separate from source verification.",
        f"Showing records {shown_start}–{shown_end} of {len(records)} · Page {page + 1}/{page_count}",
        "",
    ]
    if not records:
        lines.append("No calendar records have been ingested yet.")

    for item in selected:
        title = _review_escape(item.get("title") or "Unnamed event", limit=130)
        instrument = _review_escape(
            item.get("affected_instrument") or "USD / XAUUSD", limit=60
        )
        source = _review_escape(item.get("source_name") or "Unknown", limit=80)
        origin = (
            "Admin-entered"
            if item.get("entry_origin") == "manual"
            else "Retrieved from source"
        )
        admin_decision = _review_escape(
            item.get("review_status") or "held", limit=40
        ).upper()
        record_state = _review_escape(
            item.get("review_state") or item.get("review_status") or "held",
            limit=40,
        )
        lines.append(f"<b>{title}</b>")
        lines.append(f"Instrument: {instrument}")
        lines.append(f"Source: {source}")
        lines.append(f"Record origin: {origin}")
        lines.append(
            f"Admin review decision: {admin_decision} "
            "(review only; not permission to publish)"
        )
        if record_state != str(item.get("review_status") or "held"):
            lines.append(f"Current record status: {record_state}")
        lines.append(
            "Title check: "
            + (
                "reviewer marked checked"
                if item.get("title_verified")
                else "not verified"
            )
        )
        source_url = str(item.get("source_url") or "")
        if len(source_url) <= 350 and _safe_source_url(source_url):
            lines.append(
                f'Source link: <a href="{html.escape(source_url, quote=True)}">'
                "open source page</a>"
            )
        else:
            lines.append("Source link: unavailable or not allowlisted")

        original_time = item.get("release_time_text") or "Unavailable"
        timezone_status = str(item.get("timezone_status") or "unverified")
        if timezone_status == "verified_explicit_utc_offset":
            lines.append(
                "Original source timestamp: "
                f"<code>{_review_escape(original_time, limit=80)}</code> "
                "(explicit UTC offset)"
            )
            event_at = _parse_review_datetime(item.get("event_at_utc"))
            if event_at is not None:
                lines.append(
                    f"WAT: {event_at.astimezone(_WAT).strftime('%a, %d %b %Y %H:%M WAT')}"
                )
            else:
                lines.append("WAT: Unavailable — stored timestamp is invalid")
        else:
            lines.append(
                f"Source-listed date/time: {_review_escape(item.get('release_date_text') or 'Unavailable', limit=60)} "
                f"{_review_escape(original_time, limit=80)}"
            )
            lines.append(
                "Timezone: not verified. The time cannot be converted to WAT "
                "or used for a reminder."
            )

        retrieved = _parse_review_datetime(item.get("retrieved_at_utc"))
        if retrieved is None:
            lines.append("Last retrieved: unavailable · Retrieval recency: unknown")
        else:
            age = checked_at.astimezone(timezone.utc) - retrieved
            if age < timedelta(0):
                recency = "timestamp is in the future; needs checking"
            elif age <= CALENDAR_STALE_AFTER:
                recency = "checked within the last 24 hours"
            else:
                recency = "last checked more than 24 hours ago"
            lines.append(
                "Last retrieved: "
                f"{retrieved.strftime('%Y-%m-%d %H:%M:%S UTC')} · {recency}"
            )
        verification = str(item.get("verification_status") or "unavailable")
        if verification == "verified_schedule":
            verification_text = "official schedule entry retrieved"
        elif verification == "date_time_listed_timezone_unverified":
            verification_text = (
                "date/time listed by source; source timezone is unverified"
            )
        else:
            verification_text = verification.replace("_", " ")
        lines.append(f"Source verification: {_review_escape(verification_text, limit=100)}")
        lines.append(
            "Date check: "
            + (
                "reviewer marked checked"
                if item.get("date_verified")
                else "not verified"
            )
        )
        if timezone_status == "verified_explicit_utc_offset":
            lines.append(
                "Release-time check: "
                + ("verified" if item.get("time_verified") else "not verified")
            )
        else:
            lines.append(
                "Release-time check: not verified; no reminder time can be used"
            )
        for label, key in (
            ("Previous", "previous_value"),
            ("Forecast", "forecast_value"),
            ("Actual", "actual_value"),
            ("Impact classification", "provider_impact"),
        ):
            value = item.get(key)
            verified_key = {
                "previous_value": "previous_verified",
                "forecast_value": "forecast_verified",
                "actual_value": "actual_verified",
                "provider_impact": "impact_verified",
            }[key]
            if value in (None, ""):
                displayed_value = "UNAVAILABLE — source did not supply a value"
            elif item.get(verified_key):
                displayed_value = (
                    f"{_review_escape(value, limit=80)} (source verified)"
                )
            else:
                displayed_value = (
                    f"{_review_escape(value, limit=80)} "
                    "(present, but not independently verified)"
                )
            lines.append(
                f"{label}: {displayed_value}"
            )
        evidence_links: list[str] = []
        for label, key in (
            ("Title evidence", "title_evidence_url"),
            ("Date evidence", "date_evidence_url"),
            ("Time evidence", "time_evidence_url"),
            ("Previous evidence", "previous_evidence_url"),
            ("Forecast evidence", "forecast_evidence_url"),
            ("Actual evidence", "actual_evidence_url"),
            ("Impact evidence", "impact_evidence_url"),
        ):
            evidence_url = str(item.get(key) or "")
            if (
                evidence_url
                and evidence_url not in evidence_links
                and _safe_source_url(evidence_url)
            ):
                evidence_links.append(evidence_url)
        if evidence_links:
            if source_url in evidence_links:
                lines.append(
                    "Evidence: the same official page is linked above; it may be "
                    "a general source page, not proof of every field."
                )
            else:
                links = [
                    f'<a href="{html.escape(url, quote=True)}">evidence {index}</a>'
                    for index, url in enumerate(evidence_links[:3], start=1)
                ]
                lines.append("Evidence links: " + " · ".join(links))
        lines.append("")

    statuses = {str(row.get("source_name")): row for row in source_status}
    lines.append("<b>SOURCE ACCESS CHECKS</b>")
    for source in ("BEA", "Census", "Federal Reserve", "BLS", "DOL"):
        status = statuses.get(source)
        if status is None:
            label = (
                "UNAVAILABLE — SOURCE NOT VERIFIED"
                if source in {"BLS", "DOL"}
                else "No source check recorded"
            )
            lines.append(f"{source}: {label}.")
            continue
        checked = _parse_review_datetime(status.get("checked_at_utc"))
        raw_health = str(status.get("status") or "unknown")
        health = _review_escape(raw_health.replace("_", " "), limit=60)
        if checked is not None:
            age = checked_at.astimezone(timezone.utc) - checked
            if age < timedelta(0):
                check_recency = "check timestamp is in the future"
            elif age <= CALENDAR_STALE_AFTER:
                check_recency = "checked within the last 24 hours"
            else:
                check_recency = "last checked more than 24 hours ago"
            health += f" · last checked {checked.strftime('%Y-%m-%d %H:%M:%S UTC')} · {check_recency}"
        else:
            health += " · check time unavailable"
        failure = status.get("failure_category")
        if failure:
            health += f" · failure: {_review_escape(str(failure).replace('_', ' '), limit=50)}"
        if status.get("http_status") is not None:
            health += f" · HTTP {int(status['http_status'])}"
        lines.append(f"{html.escape(source, quote=False)}: {health}.")
    lines.extend(
        [
            "",
            "<b>HOW TO READ THIS</b>",
            "“Checked within 24 hours” refers only to retrieval time; it does not "
            "mean every event field or timezone is verified.",
            "Federal Reserve policy records are separate from this event calendar.",
            "Treasury observations are daily yields, not live gold or FX prices.",
        ]
    )
    return "\n".join(lines), page_count


def _review_escape(value: object, *, limit: int) -> str:
    text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return html.escape(text, quote=False)


def _parse_review_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def build_calendar_phase_one_report(
    records: list[dict],
    source_status: list[dict] | None = None,
) -> str:
    """Render verified schedule evidence and explicitly unavailable fields."""
    lines = [
        "📅 <b>USD &amp; GOLD — OFFICIAL RELEASE CALENDAR</b>",
        "Phase 1 source preview — not published",
        "",
    ]
    if not records:
        lines.append("No verified release entries are available.")
        return "\n".join(lines)
    for record in records:
        title = html.escape(str(record["title"]), quote=False)
        url = html.escape(str(record["source_url"]), quote=True)
        event_at_utc = record.get("event_at_utc")
        if event_at_utc:
            event_at = datetime.fromisoformat(str(event_at_utc))
            time_line = (
                f"Time: {event_at.astimezone(_WAT).strftime('%H:%M WAT')} "
                "(converted from explicit source timezone)"
            )
            schedule_status = "Schedule verified"
        else:
            time_line = (
                f"Time: {html.escape(str(record.get('release_time_text') or 'Unavailable'))} "
                "(timezone unverified; no WAT conversion)"
            )
            schedule_status = "UNAVAILABLE — TIMEZONE NOT VERIFIED"
        lines.extend(
            [
                f"<b>{title}</b>",
                f"Schedule status: {schedule_status}",
                f"Date: {html.escape(str(record['release_date_text']))}",
                time_line,
                "Provider impact: Unavailable",
                "Previous: Unavailable",
                "Forecast: Unavailable",
                "Actual: Unavailable until an official release is verified",
                f"Source: <a href=\"{url}\">official source</a>",
                "",
            ]
        )
    if source_status:
        lines.extend(["<b>SOURCE STATUS</b>"])
        for source in source_status:
            source_name = html.escape(str(source["source_name"]), quote=False)
            status = html.escape(str(source["status"]), quote=False)
            reason = source.get("failure_category")
            status_line = f"{source_name}: {status}"
            if reason:
                status_line += f" ({html.escape(str(reason), quote=False)})"
            lines.append(status_line)
    lines.append("No entry signal. NO CONFIRMATION, NO ENTRY.")
    return "\n".join(lines)


def _record_source_failure(
    calendar_repository: OfficialCalendarRepository,
    news_repository: NewsRepository,
    source_name: str,
    error: NewsSourceError,
    *,
    checked_at: datetime,
    attempts: int,
) -> None:
    calendar_repository.record_source_status(
        source_name,
        status="UNAVAILABLE — SOURCE NOT VERIFIED",
        checked_at=checked_at,
        failure_category=error.category,
        http_status=error.http_status,
        attempts=attempts,
    )
    dedupe_date = checked_at.astimezone(_WAT).date().isoformat()
    payload = (
        f"{source_name}: UNAVAILABLE — SOURCE NOT VERIFIED. "
        f"Category: {error.category}; HTTP status: "
        f"{error.http_status if error.http_status is not None else 'unavailable'}. "
        "Affected release entries are held; no figures or times will be inferred."
    )
    news_repository.enqueue_notification(
        f"usd_calendar_source:{source_name}:{dedupe_date}:{error.category}",
        "calendar_source_unavailable",
        payload,
    )


def fetch_and_store_official_schedules(
    database_path: str | Path,
    *,
    now: datetime | None = None,
    opener=urlopen,
    sleep=time.sleep,
) -> dict[str, int | str]:
    """Fetch BEA/Census official schedules and record BLS/DOL source failures.

    This is an explicit ingestion operation, not an automated job. It never
    sends Telegram messages, and source failures create a persistent admin
    notification for later delivery after destination approval.
    """
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    calendar_repo = OfficialCalendarRepository(database_path)
    news_repo = NewsRepository(database_path)
    result: dict[str, int | str] = {}
    start_at = observed.astimezone(timezone.utc)
    end_at = start_at + timedelta(days=120)

    sources = (
        (
            "BEA",
            BEA_RELEASE_DATES_URL,
            lambda body: parse_bea_release_dates(
                json.loads(body.decode("utf-8")),
                retrieved_at=observed,
                start_at=start_at,
                end_at=end_at,
            ),
        ),
        (
            "Census",
            CENSUS_RELEASE_CALENDAR_URL,
            lambda body: parse_census_retail_calendar(body, retrieved_at=observed),
        ),
        (
            "BLS",
            BLS_RELEASE_SCHEDULE_URL,
            lambda body: parse_bls_release_ics(
                body,
                retrieved_at=observed,
                start_at=start_at,
                end_at=end_at,
            ),
        ),
        ("DOL", DOL_CLAIMS_SCHEDULE_URL, None),
    )
    for source_name, url, parser in sources:
        attempts = 0
        try:
            def fetch():
                nonlocal attempts
                attempts += 1
                return _fetch_bytes(url, opener=opener)[0]

            body = fetch_with_bounded_backoff(fetch, sleep=sleep)
            if parser is None:
                raise NewsSourceError("source_format_not_verified")
            records = parser(body)
            calendar_repo.save_records(records)
            calendar_repo.record_source_status(
                source_name,
                status="verified_schedule",
                checked_at=observed,
                attempts=attempts,
            )
            result[source_name] = len(records)
        except (NewsSourceError, UnicodeDecodeError, json.JSONDecodeError) as error:
            if not isinstance(error, NewsSourceError):
                error = NewsSourceError("malformed_source_response")
            _record_source_failure(
                calendar_repo,
                news_repo,
                source_name,
                error,
                checked_at=observed,
                attempts=max(1, attempts),
            )
            result[source_name] = "UNAVAILABLE — SOURCE NOT VERIFIED"
    return result


__all__ = [
    "BEA_RELEASE_DATES_URL",
    "BLS_RELEASE_SCHEDULE_URL",
    "CENSUS_RELEASE_CALENDAR_URL",
    "DOL_CLAIMS_SCHEDULE_URL",
    "FED_FOMC_CALENDAR_URL",
    "OfficialCalendarRecord",
    "OfficialCalendarRepository",
    "build_calendar_phase_one_report",
    "fetch_and_store_official_schedules",
    "fetch_with_bounded_backoff",
    "parse_bea_release_dates",
    "parse_bls_release_ics",
    "parse_census_retail_calendar",
    "parse_fed_fomc_calendar",
]
