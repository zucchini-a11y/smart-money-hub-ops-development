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
import socket
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .news_intelligence import NewsRepository, NewsSourceError

logger = logging.getLogger(__name__)

BEA_RELEASE_DATES_URL = "https://apps.bea.gov/API/signup/release_dates.json"
CENSUS_RELEASE_CALENDAR_URL = (
    "https://www.census.gov/economic-indicators/calendar-listview.html"
)
BLS_RELEASE_SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/"
DOL_CLAIMS_SCHEDULE_URL = "https://www.dol.gov/agencies/eta/ui/claims"

_ALLOWED_HOSTS = frozenset(
    {
        "apps.bea.gov",
        "www.census.gov",
        "www.bls.gov",
        "www.dol.gov",
    }
)
_WAT = ZoneInfo("Africa/Lagos")
_MAX_BODY_BYTES = 4_000_000
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
            "Accept": "application/json, text/html",
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
                    external_id=_event_id("bea", title, event_at.isoformat()),
                    source_name="U.S. Bureau of Economic Analysis",
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


class OfficialCalendarRepository:
    """Persistent source evidence/status; never sends Telegram messages."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
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
        with sqlite3.connect(self.database_path) as connection:
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
        with sqlite3.connect(self.database_path) as connection:
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
                        timezone_status, previous_value, forecast_value,
                        actual_value, provider_impact, verification_status,
                        retrieved_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(external_id) DO UPDATE SET
                        source_url=excluded.source_url,
                        release_date_text=excluded.release_date_text,
                        release_time_text=excluded.release_time_text,
                        event_at_utc=excluded.event_at_utc,
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
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM usd_calendar_source_events "
                    "ORDER BY release_date_text, release_time_text"
                ).fetchall()
            ]

    def list_source_status(self) -> list[dict]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM usd_calendar_source_status ORDER BY source_name"
                ).fetchall()
            ]


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
        ("BLS", BLS_RELEASE_SCHEDULE_URL, None),
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
    "OfficialCalendarRecord",
    "OfficialCalendarRepository",
    "build_calendar_phase_one_report",
    "fetch_and_store_official_schedules",
    "fetch_with_bounded_backoff",
    "parse_bea_release_dates",
    "parse_census_retail_calendar",
]
