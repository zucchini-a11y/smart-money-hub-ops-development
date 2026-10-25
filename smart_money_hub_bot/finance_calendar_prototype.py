"""Isolated Finance Calendar evaluation tools.

This module is intentionally not imported by the production bot, scheduler,
publisher, or production database. It is a read-only secondary-source
prototype: provider records remain candidates until matched to explicit
official-source evidence.
"""

from __future__ import annotations

import html
import json
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

API_BASE = "https://www.financecalendar.com/wp-json/fc/v1"
API_OVERVIEW_URL = "https://www.financecalendar.com/api/"
PROVIDER_ATTRIBUTION_URL = "https://www.financecalendar.com"
BEA_RELEASE_DATES_URL = "https://apps.bea.gov/API/signup/release_dates.json"
FED_FOMC_CALENDAR_URL = (
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
)
BLS_RELEASE_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
CENSUS_RELEASE_CALENDAR_URL = (
    "https://www.census.gov/economic-indicators/calendar-listview.html"
)
_USER_AGENT = "SmartMoneyHub-FinanceCalendar-Prototype/1.0"
_MAX_BODY_BYTES = 4_000_000
_MAX_RETRY_AFTER_SECONDS = 20.0
_WAT = ZoneInfo("Africa/Lagos")

# Deliberately narrow allowlist. Do not replace this with a broad "US" filter:
# the provider also returns unrelated auctions, energy data, and other events.
ALLOWED_SERIES_CODES = frozenset(
    {
        "fomc",
        "fomc-minutes",
        "us-gdp",
        "us-pce",
        "us-cpi",
        "us-ppi",
        "us-nfp",
        "us-jobless-claims",
        "us-retail-sales",
        "us-durable-goods-orders",
        "us-advance-economic-indicators",
    }
)
_SOURCE_BY_SERIES = {
    "fomc": "fed",
    "fomc-minutes": "fed",
    "us-gdp": "bea",
    "us-pce": "bea",
    "us-cpi": "bls",
    "us-ppi": "bls",
    "us-nfp": "bls",
    "us-jobless-claims": "dol",
    "us-retail-sales": "census",
    "us-durable-goods-orders": "census",
    "us-advance-economic-indicators": "census",
}
_SOURCE_HOSTS = {
    "bea": frozenset({"apps.bea.gov", "www.bea.gov", "bea.gov"}),
    "fed": frozenset({"www.federalreserve.gov", "federalreserve.gov"}),
    "bls": frozenset({"www.bls.gov", "bls.gov"}),
    "dol": frozenset(
        {"oui.doleta.gov", "www.dol.gov", "dol.gov", "www.doleta.gov"}
    ),
    "census": frozenset({"www.census.gov", "census.gov"}),
}
_ALLOWLISTED_FETCH_HOSTS = frozenset(
    {
        "www.financecalendar.com",
        "apps.bea.gov",
        "www.federalreserve.gov",
        "www.bls.gov",
        "www.census.gov",
    }
)
_SIGNATURE_FIELDS = (
    "date",
    "release_at_utc",
    "release_tz",
    "time_precision",
    "status",
    "impact",
    "prior",
    "consensus",
    "actual",
    "source_name",
    "source_url",
    "source_license",
    "source_rights",
    "last_verified_at",
    "data_stale",
    "updated_at",
)


class FinanceCalendarError(RuntimeError):
    """Sanitized provider/source error without URLs, bodies, or credentials."""

    def __init__(self, category: str, http_status: int | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.http_status = http_status


def _safe_fetch_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWLISTED_FETCH_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def _parse_retry_after(
    value: str | None, *, now: datetime
) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - now.astimezone(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if seconds < 0:
        return 0.0
    return seconds


def _get_bytes(
    url: str,
    *,
    opener: Callable = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
    max_attempts: int = 3,
) -> tuple[bytes, dict[str, str]]:
    """Fetch an allowlisted URL with bounded retries and Retry-After support."""
    if not _safe_fetch_url(url):
        raise FinanceCalendarError("source_url_not_allowlisted")
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3.")
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("now must be timezone-aware.")

    request = Request(
        url,
        headers={
            "Accept": "application/json, text/html, text/calendar, */*",
            "User-Agent": _USER_AGENT,
        },
    )
    for attempt in range(max_attempts):
        retry_delay: float | None = None
        try:
            with opener(request, timeout=12) as response:
                body = response.read(_MAX_BODY_BYTES + 1)
                status = int(getattr(response, "status", 200))
                headers = {
                    str(key): str(value)
                    for key, value in getattr(response, "headers", {}).items()
                }
            if len(body) > _MAX_BODY_BYTES:
                raise FinanceCalendarError("response_too_large", status)
            if not 200 <= status < 300:
                raise FinanceCalendarError("http_error", status)
            return body, headers
        except HTTPError as error:
            status = int(error.code)
            response_headers = error.headers or {}
            if status == 429:
                retry_delay = _parse_retry_after(
                    response_headers.get("Retry-After"), now=observed
                )
                if retry_delay is None:
                    retry_delay = min(1.0 * (2**attempt), 4.0)
                if retry_delay > _MAX_RETRY_AFTER_SECONDS:
                    raise FinanceCalendarError(
                        "retry_after_exceeds_bound", status
                    ) from None
                category = "rate_limit"
            elif status in {500, 502, 503, 504}:
                retry_delay = min(1.0 * (2**attempt), 4.0)
                category = "service_unavailable"
            else:
                category = {
                    401: "authentication_error",
                    403: "permission_error",
                    404: "not_found",
                }.get(status, "http_error")
            if retry_delay is None or attempt + 1 >= max_attempts:
                raise FinanceCalendarError(category, status) from None
        except (TimeoutError, socket.timeout):
            if attempt + 1 >= max_attempts:
                raise FinanceCalendarError("timeout") from None
            retry_delay = min(1.0 * (2**attempt), 4.0)
        except URLError as error:
            reason = error.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                category = "timeout"
            else:
                category = "network_error"
            if attempt + 1 >= max_attempts:
                raise FinanceCalendarError(category) from None
            retry_delay = min(1.0 * (2**attempt), 4.0)
        if retry_delay is not None:
            sleep(retry_delay)
    raise AssertionError("Unreachable retry state.")


def _decode_json(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FinanceCalendarError("malformed_json") from None
    if not isinstance(payload, dict):
        raise FinanceCalendarError("unexpected_json_shape")
    return payload


class FinanceCalendarPrototypeClient:
    """Read-only client for the public, keyless Finance Calendar API."""

    def __init__(
        self,
        *,
        opener: Callable = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        now: datetime | None = None,
    ) -> None:
        self.opener = opener
        self.sleep = sleep
        self.now = now

    def _get_json(self, url: str) -> dict[str, Any]:
        body, _headers = _get_bytes(
            url, opener=self.opener, sleep=self.sleep, now=self.now
        )
        return _decode_json(body)

    def get_calendar(self, start: date, end: date) -> dict[str, Any]:
        if end < start or (end - start).days > 91:
            raise ValueError("Calendar range must be 1–92 days.")
        query = urlencode(
            {
                "country": "US",
                "from": start.isoformat(),
                "to": end.isoformat(),
                "limit": 500,
                "format": "json",
            }
        )
        return self._get_json(f"{API_BASE}/calendar?{query}")

    def get_status(self) -> dict[str, Any]:
        return self._get_json(f"{API_BASE}/status")


@dataclass(frozen=True)
class OfficialScheduleEvidence:
    series_code: str
    event_date: date
    source_name: str
    source_url: str
    retrieved_at: datetime
    release_at_utc: datetime | None = None
    source_timezone: str | None = None
    reference_period: str | None = None

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("Official retrieval time must be timezone-aware.")
        if self.release_at_utc is not None and self.release_at_utc.tzinfo is None:
            raise ValueError("Official event time must be timezone-aware.")


def parse_bea_schedule(
    payload: dict[str, Any], *, retrieved_at: datetime
) -> list[OfficialScheduleEvidence]:
    """Parse only the official BEA GDP and Personal Income/Outlays schedule."""
    mapping = {
        "Gross Domestic Product": "us-gdp",
        "Personal Income and Outlays": "us-pce",
    }
    evidence: list[OfficialScheduleEvidence] = []
    for title, series_code in mapping.items():
        record = payload.get(title)
        release_dates = record.get("release_dates") if isinstance(record, dict) else None
        if not isinstance(release_dates, list):
            continue
        for raw in release_dates:
            if not isinstance(raw, str):
                continue
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                continue
            utc_time = parsed.astimezone(timezone.utc)
            evidence.append(
                OfficialScheduleEvidence(
                    series_code=series_code,
                    event_date=utc_time.date(),
                    source_name="U.S. Bureau of Economic Analysis",
                    source_url="https://apps.bea.gov/API/signup/release_dates.json",
                    retrieved_at=retrieved_at,
                    release_at_utc=utc_time,
                    source_timezone="UTC",
                )
            )
    return evidence


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden and data.strip():
            self.parts.append(" ".join(data.split()))


class _CensusCalendarParser(HTMLParser):
    """Read event rows from the Census calendar without assuming its timezone."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_calendar = False
        self.in_row = False
        self.in_cell = False
        self.cells: list[str] = []
        self.current = ""
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "calendar":
            self.in_calendar = True
        elif self.in_calendar and tag == "tr":
            self.in_row = True
            self.cells = []
        elif self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.current = ""

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_cell:
            self.cells.append(" ".join(self.current.split()))
            self.current = ""
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.cells:
                self.rows.append(self.cells)
            self.cells = []
            self.in_row = False
        elif tag == "table" and self.in_calendar:
            self.in_calendar = False


def parse_census_release_calendar(
    body: bytes, *, retrieved_at: datetime
) -> list[OfficialScheduleEvidence]:
    """Verify Census event dates only; its calendar does not verify a timezone."""
    parser = _CensusCalendarParser()
    parser.feed(body.decode("utf-8", "replace"))
    evidence: list[OfficialScheduleEvidence] = []
    mappings = (
        (
            ("advance monthly sales for retail and food services",),
            "us-retail-sales",
        ),
        (
            ("durable goods", "manufacturers' shipments"),
            "us-durable-goods-orders",
        ),
        (
            ("advance economic indicators",),
            "us-advance-economic-indicators",
        ),
    )
    for cells in parser.rows:
        if len(cells) < 2:
            continue
        title = cells[0].casefold()
        code = next(
            (
                series_code
                for terms, series_code in mappings
                if all(term in title for term in terms)
            ),
            None,
        )
        if not code:
            continue
        event_date = None
        for date_format in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
            try:
                event_date = datetime.strptime(cells[1], date_format).date()
                break
            except ValueError:
                continue
        if event_date:
            evidence.append(
                OfficialScheduleEvidence(
                    series_code=code,
                    event_date=event_date,
                    source_name="U.S. Census Bureau",
                    source_url=CENSUS_RELEASE_CALENDAR_URL,
                    retrieved_at=retrieved_at,
                    release_at_utc=None,
                    source_timezone=None,
                    reference_period=cells[3] if len(cells) > 3 else None,
                )
            )
    return evidence


def parse_fed_fomc_calendar(
    body: bytes, *, retrieved_at: datetime
) -> list[OfficialScheduleEvidence]:
    """Verify FOMC meeting dates from the Fed calendar, not release times."""
    parser = _VisibleTextParser()
    parser.feed(body.decode("utf-8", "replace"))
    text = " ".join(parser.parts)
    section_start = text.find("2026 FOMC Meetings")
    if section_start < 0:
        return []
    section_end = text.find("2025 FOMC Meetings", section_start)
    section = text[section_start : section_end if section_end >= 0 else None]
    month_numbers = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }
    result: list[OfficialScheduleEvidence] = []
    for match in re.finditer(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\b",
        section,
    ):
        month = month_numbers[match.group(1)]
        meeting_end = date(2026, month, int(match.group(3)))
        result.append(
            OfficialScheduleEvidence(
                series_code="fomc",
                event_date=meeting_end,
                source_name="Board of Governors of the Federal Reserve System",
                source_url=FED_FOMC_CALENDAR_URL,
                retrieved_at=retrieved_at,
                release_at_utc=None,
                source_timezone=None,
            )
        )
    return result


def _parse_ics_datetime(
    property_line: str,
) -> tuple[date, datetime | None, str | None] | None:
    if ":" not in property_line:
        return None
    left, value = property_line.split(":", 1)
    params = left.split(";")[1:]
    tzid = next((p.split("=", 1)[1] for p in params if p.startswith("TZID=")), None)
    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").date(), None, tzid
    if re.fullmatch(r"\d{8}T\d{6}Z", value):
        utc_time = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
        return utc_time.date(), utc_time, "UTC"
    if not re.fullmatch(r"\d{8}T\d{6}", value) or not tzid:
        return None
    try:
        source_zone = ZoneInfo(tzid)
        source_time = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(
            tzinfo=source_zone
        )
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return (
        source_time.date(),
        source_time.astimezone(timezone.utc),
        tzid,
    )


def parse_bls_release_ics(
    body: bytes, *, retrieved_at: datetime
) -> list[OfficialScheduleEvidence]:
    """Parse matching BLS release dates/times when the official ICS is accessible."""
    text = body.decode("utf-8", "replace")
    text = re.sub(r"\r?\n[ \t]", "", text)
    evidence: list[OfficialScheduleEvidence] = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        summary_match = re.search(r"^SUMMARY[^:]*:(.*)$", block, re.M)
        start_match = re.search(r"^DTSTART[^:]*:.*$", block, re.M)
        if not summary_match or not start_match:
            continue
        summary = summary_match.group(1).strip().casefold()
        series_code = next(
            (
                code
                for phrases, code in (
                    (("employment situation", "nonfarm payroll"), "us-nfp"),
                    (("consumer price index", "cpi"), "us-cpi"),
                    (("producer price index", "ppi"), "us-ppi"),
                )
                if any(phrase in summary for phrase in phrases)
            ),
            None,
        )
        if not series_code:
            continue
        parsed = _parse_ics_datetime(start_match.group(0))
        if parsed is None:
            continue
        event_date, release_at_utc, source_timezone = parsed
        evidence.append(
            OfficialScheduleEvidence(
                series_code=series_code,
                event_date=event_date,
                source_name="U.S. Bureau of Labor Statistics",
                source_url=BLS_RELEASE_ICS_URL,
                retrieved_at=retrieved_at,
                release_at_utc=release_at_utc,
                source_timezone=source_timezone,
            )
        )
    return evidence


def fetch_official_evidence(
    series_codes: Iterable[str],
    *,
    now: datetime,
    opener: Callable = urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[OfficialScheduleEvidence], dict[str, str]]:
    """Fetch only official calendars needed for requested allowlisted series."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    requested = set(series_codes) & ALLOWED_SERIES_CODES
    evidence: list[OfficialScheduleEvidence] = []
    failures: dict[str, str] = {}

    def fetch(url: str, label: str) -> bytes | None:
        try:
            body, _ = _get_bytes(url, opener=opener, sleep=sleep, now=now)
            return body
        except FinanceCalendarError as error:
            status_text = (
                f"_{error.http_status}" if error.http_status is not None else ""
            )
            failures[label] = f"{error.category}{status_text}"
            return None

    if requested & {"us-gdp", "us-pce"}:
        body = fetch(BEA_RELEASE_DATES_URL, "BEA")
        if body is not None:
            try:
                evidence.extend(
                    parse_bea_schedule(_decode_json(body), retrieved_at=now)
                )
            except FinanceCalendarError as error:
                failures["BEA"] = error.category

    if "fomc" in requested:
        body = fetch(FED_FOMC_CALENDAR_URL, "Federal Reserve")
        if body is not None:
            evidence.extend(parse_fed_fomc_calendar(body, retrieved_at=now))
            if not any(item.series_code == "fomc" for item in evidence):
                failures["Federal Reserve"] = "fomc_dates_not_found"

    if requested & {"us-cpi", "us-ppi", "us-nfp"}:
        body = fetch(BLS_RELEASE_ICS_URL, "BLS")
        if body is not None:
            evidence.extend(parse_bls_release_ics(body, retrieved_at=now))
            wanted = requested & {"us-cpi", "us-ppi", "us-nfp"}
            if not any(item.series_code in wanted for item in evidence):
                failures["BLS"] = "matching_release_not_found"

    if requested & {
        "us-retail-sales",
        "us-durable-goods-orders",
        "us-advance-economic-indicators",
    }:
        body = fetch(CENSUS_RELEASE_CALENDAR_URL, "Census")
        if body is not None:
            evidence.extend(parse_census_release_calendar(body, retrieved_at=now))
            wanted = requested & {
                "us-retail-sales",
                "us-durable-goods-orders",
                "us-advance-economic-indicators",
            }
            if not any(item.series_code in wanted for item in evidence):
                failures["Census"] = "matching_release_not_found"

    if "us-jobless-claims" in requested:
        # The provider's linked DOL archive is not itself a verified forward
        # release schedule. Do not infer the recurring weekday/time.
        failures["DOL"] = "official_forward_schedule_not_verified"

    return evidence, failures


@dataclass
class CalendarCandidate:
    event: dict[str, Any]
    verification_status: str
    reason: str
    provider_health_status: str
    source_health_status: str
    source_freshness_status: str
    official_source_name: str | None = None
    official_source_url: str | None = None
    wat_time: datetime | None = None
    source_license_notice: Any = None
    source_rights_notice: Any = None
    source_rights_status: str = "none_supplied_in_record"


@dataclass
class PrototypeEvaluation:
    candidates: list[CalendarCandidate] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    duplicate_count: int = 0
    excluded_count: int = 0
    provider_health_status: str = "unavailable"
    provider_snapshot_age_seconds: int | None = None
    provider_attribution_present: bool = False
    source_failures: dict[str, str] = field(default_factory=dict)

    @property
    def verified_count(self) -> int:
        return sum(
            candidate.verification_status
            in {"verified_date_and_time", "verified_date_only"}
            for candidate in self.candidates
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _record_identity(event: dict[str, Any]) -> tuple[Any, ...]:
    event_id = str(event.get("id") or "")
    return (
        event.get("source_id") or "",
        event.get("series_code") or "",
        ("id", event_id) if event_id else ("date", event.get("date") or ""),
        event.get("release_stage") or "",
        "" if event_id else event.get("period") or "",
    )


def _record_signature(event: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        json.dumps(event.get(field_name), sort_keys=True, ensure_ascii=True)
        for field_name in _SIGNATURE_FIELDS
    )


def _deduplicate(
    events: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(_record_identity(event), []).append(event)
    selected: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    duplicates = 0
    for identity, rows in grouped.items():
        signatures = {_record_signature(row) for row in rows}
        if len(signatures) > 1:
            conflicts.append(
                {
                    "identity": identity,
                    "category": "duplicate_provider_records_conflict",
                    "count": len(rows),
                }
            )
            continue
        selected.append(rows[0])
        duplicates += len(rows) - 1
    return selected, conflicts, duplicates


def _source_health_rows(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("source_id")): row
        for row in status.get("source_health", [])
        if isinstance(row, dict) and row.get("source_id")
    }


def _matches_official(
    event: dict[str, Any],
    evidence: list[OfficialScheduleEvidence],
    *,
    now: datetime,
    max_age: timedelta,
) -> tuple[str, str, OfficialScheduleEvidence | None]:
    code = str(event.get("series_code") or "")
    try:
        event_date = date.fromisoformat(str(event.get("date")))
    except ValueError:
        return "held", "invalid_event_date", None
    matches = [
        item
        for item in evidence
        if item.series_code == code
        and (
            not item.reference_period
            or not event.get("period")
            or item.reference_period.casefold() == str(event.get("period")).casefold()
        )
        and item.event_date == event_date
    ]
    if not matches:
        period_matches = [
            item
            for item in evidence
            if item.series_code == code
            and event.get("period")
            and item.reference_period
            and item.reference_period.casefold() == str(event.get("period")).casefold()
        ]
        if period_matches:
            return "conflict", "official_date_mismatch", None
        return "held", "official_source_not_verified", None
    for item in matches:
        if now.astimezone(timezone.utc) - item.retrieved_at.astimezone(
            timezone.utc
        ) > max_age:
            continue
        provider_time = _parse_timestamp(event.get("release_at_utc"))
        if item.release_at_utc is None:
            return "verified_date_only", "official_date_match_time_unverified", item
        if provider_time is None:
            return "verified_date_only", "provider_time_missing", item
        if provider_time.astimezone(timezone.utc) != item.release_at_utc.astimezone(
            timezone.utc
        ):
            return "conflict", "official_time_mismatch", item
        return "verified_date_and_time", "official_date_time_match", item
    return "held", "official_evidence_stale", None


def evaluate_provider_records(
    calendar: dict[str, Any],
    provider_status: dict[str, Any],
    official_evidence: Iterable[OfficialScheduleEvidence],
    *,
    now: datetime,
    source_failures: dict[str, str] | None = None,
    max_age: timedelta = timedelta(hours=24),
) -> PrototypeEvaluation:
    """Evaluate allowlisted provider rows without trusting provider verification."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    result = PrototypeEvaluation(
        source_failures=dict(source_failures or {}),
        provider_attribution_present=(
            isinstance(calendar.get("attribution"), dict)
            and calendar.get("attribution", {}).get("source") == "financecalendar.com"
            and "financecalendar.com"
            in str(calendar.get("attribution", {}).get("terms") or "")
        ),
    )
    result.provider_health_status = (
        "healthy"
        if provider_status.get("ok") is True
        else "degraded"
        if provider_status
        else "unavailable"
    )
    snapshot = provider_status.get("snapshot")
    snapshot_age = snapshot.get("age_seconds") if isinstance(snapshot, dict) else None
    if isinstance(snapshot_age, (int, float)) and snapshot_age >= 0:
        result.provider_snapshot_age_seconds = int(snapshot_age)
    snapshot_generated = _parse_timestamp(
        snapshot.get("generated_at") if isinstance(snapshot, dict) else None
    )
    snapshot_fresh = bool(
        snapshot_generated
        and now.astimezone(timezone.utc)
        - snapshot_generated.astimezone(timezone.utc)
        <= max_age
    )
    health_rows = _source_health_rows(provider_status)
    raw_events = calendar.get("events")
    if not isinstance(raw_events, list):
        raw_events = []
    allowlisted: list[dict[str, Any]] = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        code = str(event.get("series_code") or "").casefold()
        title = str(event.get("title") or event.get("name") or "").casefold()
        if "ism" in title or "ism" in code or code not in ALLOWED_SERIES_CODES:
            result.excluded_count += 1
            continue
        if event.get("country") != "US":
            result.excluded_count += 1
            continue
        allowlisted.append(event)
    unique, conflicts, duplicates = _deduplicate(allowlisted)
    result.conflicts.extend(conflicts)
    result.duplicate_count = duplicates
    evidence = list(official_evidence)

    for event in unique:
        code = str(event.get("series_code") or "")
        source_id = _SOURCE_BY_SERIES.get(code, "")
        health = health_rows.get(source_id, {})
        source_health_status = str(health.get("status") or "unavailable")
        freshness = "fresh" if snapshot_fresh else "stale_or_unknown_snapshot"
        record_verified_at = _parse_timestamp(event.get("last_verified_at"))
        age_at = now.astimezone(timezone.utc)
        record_age_fresh = bool(
            record_verified_at
            and timedelta(0)
            <= age_at - record_verified_at.astimezone(timezone.utc)
            <= max_age
            and event.get("data_stale") is False
        )
        if not record_age_fresh:
            freshness = "stale_or_unverified_record"

        source_url = event.get("source_url")
        parsed_url = urlparse(source_url) if isinstance(source_url, str) else None
        allowed_hosts = _SOURCE_HOSTS.get(source_id, frozenset())
        link_ok = bool(
            parsed_url
            and parsed_url.scheme == "https"
            and parsed_url.hostname in allowed_hosts
            and parsed_url.username is None
            and parsed_url.password is None
        )

        if not result.provider_attribution_present:
            status, reason = "held", "provider_attribution_missing"
            official = None
        elif not snapshot_fresh:
            status, reason = "held", "provider_snapshot_stale_or_unknown"
            official = None
        elif not record_age_fresh:
            status, reason = "held", "record_stale_or_unverified"
            official = None
        elif source_health_status != "success":
            status, reason = "held", "provider_source_health_not_success"
            official = None
        elif not link_ok:
            status, reason = "held", "original_source_link_missing_or_invalid"
            official = None
        else:
            status, reason, official = _matches_official(
                event, evidence, now=now, max_age=max_age
            )
            if status.startswith("verified") and not result.provider_attribution_present:
                status, reason, official = "held", "provider_attribution_missing", None

        wat_time: datetime | None = None
        if status == "verified_date_and_time" and official:
            wat_time = official.release_at_utc.astimezone(_WAT)
        result.candidates.append(
            CalendarCandidate(
                event=event,
                verification_status=status,
                reason=reason,
                provider_health_status=result.provider_health_status,
                source_health_status=source_health_status,
                source_freshness_status=freshness,
                official_source_name=official.source_name if official else None,
                official_source_url=official.source_url if official else None,
                wat_time=wat_time,
                source_license_notice=event.get("source_license"),
                source_rights_notice=(
                    event.get("source_rights")
                    or next(
                        (
                            observation.get("source_rights")
                            for observation in event.get("observations", [])
                            if isinstance(observation, dict)
                            and observation.get("source_rights")
                        ),
                        None,
                    )
                ),
                source_rights_status=(
                    "supplied"
                    if event.get("source_license")
                    or event.get("source_rights")
                    or any(
                        isinstance(observation, dict)
                        and observation.get("source_rights")
                        for observation in event.get("observations", [])
                    )
                    else "none_supplied_in_record"
                ),
            )
        )
    return result


def render_weekly_preview(
    evaluation: PrototypeEvaluation,
    *,
    week_start: date,
    week_end: date,
) -> str:
    """Render a separate attributed, non-publishing preview."""
    rows = [
        candidate
        for candidate in evaluation.candidates
        if candidate.verification_status
        in {"verified_date_and_time", "verified_date_only"}
        and week_start.isoformat() <= str(candidate.event.get("date")) <= week_end.isoformat()
    ]
    rows.sort(
        key=lambda item: (
            str(item.event.get("date")),
            item.wat_time.isoformat() if item.wat_time else "",
            str(item.event.get("series_code")),
        )
    )
    lines = [
        "<b>NON-PRODUCTION TEST PREVIEW — NOT PUBLISHED</b>",
        "<b>USD &amp; GOLD — WEEKLY ECONOMIC CALENDAR</b>",
        f"{week_start.strftime('%d %b')}–{week_end.strftime('%d %b %Y')}",
        "",
        "Finance Calendar is a secondary event-discovery source. "
        "Official-source matches are shown below.",
        "",
    ]
    if not rows:
        lines.append("No events passed the official-source checks for this week.")
    for candidate in rows:
        event = candidate.event
        title = html.escape(str(event.get("title") or event.get("name") or "U.S. event"))
        event_date = date.fromisoformat(str(event["date"]))
        date_line = event_date.strftime("%a, %d %b %Y")
        if candidate.wat_time:
            date_line += f" · {candidate.wat_time.strftime('%H:%M')} WAT"
        else:
            date_line += " · time unavailable (official date only)"
        lines.extend(
            [
                f"<b>{date_line}</b>",
                f"🇺🇸 {title}",
                f"Source: <a href=\"{html.escape(candidate.official_source_url or '', quote=True)}\">"
                f"{html.escape(candidate.official_source_name or 'Official source')}</a>",
                f"Finance Calendar impact: {html.escape(str(event.get('impact') or 'Unavailable'))} "
                "(provider-supplied, not an official-source rating).",
                "Previous: Unavailable unless separately verified from the official source.",
                "Forecast/consensus: Unavailable; the provider says consensus estimates are not currently collected.",
                "Actual: Not yet released for this scheduled event.",
                "",
            ]
        )
        if candidate.source_license_notice:
            lines.append(
                "Source licence notice: "
                + html.escape(str(candidate.source_license_notice))
            )
        if candidate.source_rights_notice:
            lines.append(
                "Source rights notice: "
                + html.escape(
                    json.dumps(candidate.source_rights_notice, ensure_ascii=False)
                )
            )
        else:
            lines.append(
                "Source-specific rights notice: none supplied in this record; "
                "Finance Calendar attribution still applies."
            )
        lines.append(
            "Possible relevance: This release may inform U.S. growth, inflation, "
            "or policy expectations that can affect USD and gold. The reaction is "
            "uncertain; news is not entry confirmation."
        )
        lines.append("")
    if evaluation.provider_health_status != "healthy":
        lines.extend(
            [
                "⚠️ Provider-wide health is degraded; each included event was "
                "separately matched to fresh official-source evidence.",
                "",
            ]
        )
    lines.extend(
        [
            "⚠️ <b>NO CONFIRMATION, NO ENTRY.</b>",
            "Calendar data: <a href=\"https://www.financecalendar.com\">Finance Calendar</a>.",
        ]
    )
    return "\n".join(lines)


def build_source_comparison_report(
    evaluation: PrototypeEvaluation,
    *,
    generated_at: datetime,
) -> str:
    """Summarize provider health and every candidate's safe review status."""
    if generated_at.tzinfo is None:
        raise ValueError("generated_at must be timezone-aware.")
    lines = [
        "NON-PRODUCTION SOURCE COMPARISON — ADMIN REVIEW",
        f"Generated: {generated_at.astimezone(timezone.utc).isoformat()}",
        f"Provider health: {evaluation.provider_health_status}",
        "Provider attribution present: "
        + ("yes" if evaluation.provider_attribution_present else "no"),
        "Snapshot age seconds: "
        + (
            str(evaluation.provider_snapshot_age_seconds)
            if evaluation.provider_snapshot_age_seconds is not None
            else "unavailable"
        ),
        f"Allowlisted candidates: {len(evaluation.candidates)}",
        f"Verified against official evidence: {evaluation.verified_count}",
        f"Exact duplicates removed: {evaluation.duplicate_count}",
        f"Out-of-scope records excluded: {evaluation.excluded_count}",
        f"Conflicts: {len(evaluation.conflicts)}",
        "",
    ]
    for candidate in evaluation.candidates:
        event = candidate.event
        lines.append(
            " | ".join(
                (
                    str(event.get("series_code") or "unknown-series"),
                    str(event.get("date") or "date-unavailable"),
                    candidate.verification_status,
                    candidate.reason,
                    f"provider-source-health={candidate.source_health_status}",
                    f"freshness={candidate.source_freshness_status}",
                    f"provider-impact={event.get('impact') or 'unavailable'}",
                    f"previous={event.get('prior') or 'unavailable'}",
                    f"forecast={event.get('consensus') or 'unavailable'}",
                    f"actual={event.get('actual') or 'unavailable'}",
                )
            )
        )
        if candidate.source_license_notice or candidate.source_rights_notice:
            lines.append(
                "  source-specific rights notice retained: "
                + json.dumps(
                    {
                        "source_license": candidate.source_license_notice,
                        "source_rights": candidate.source_rights_notice,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            lines.append("  source-specific rights notice: none supplied in record")
    for conflict in evaluation.conflicts:
        lines.append(
            "CONFLICT: "
            + json.dumps(conflict, ensure_ascii=False, sort_keys=True)
        )
    for source_name, category in sorted(evaluation.source_failures.items()):
        lines.append(f"OFFICIAL SOURCE CHECK FAILED: {source_name}: {category}")
    lines.extend(
        [
            "",
            "Finance Calendar attribution: "
            "https://www.financecalendar.com",
            "Provider confirmation, data_stale=false, or HTTP 200 alone is not "
            "official verification.",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "ALLOWED_SERIES_CODES",
    "API_BASE",
    "API_OVERVIEW_URL",
    "BEA_RELEASE_DATES_URL",
    "BLS_RELEASE_ICS_URL",
    "CENSUS_RELEASE_CALENDAR_URL",
    "FED_FOMC_CALENDAR_URL",
    "CalendarCandidate",
    "FinanceCalendarError",
    "FinanceCalendarPrototypeClient",
    "OfficialScheduleEvidence",
    "PrototypeEvaluation",
    "_get_bytes",
    "build_source_comparison_report",
    "evaluate_provider_records",
    "fetch_official_evidence",
    "parse_bea_schedule",
    "parse_bls_release_ics",
    "parse_census_release_calendar",
    "parse_fed_fomc_calendar",
    "render_weekly_preview",
]
