"""Admin-only management tools for the official USD/gold release calendar.

This module stores review decisions and field-level evidence. It is deliberately
not connected to the scheduler or any Telegram channel publisher.
"""

from __future__ import annotations

import hashlib
import html
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .economic_calendar_phase1 import (
    CALENDAR_STALE_AFTER,
    OfficialCalendarRepository,
    OfficialCalendarReadRepository,
)

WAT = ZoneInfo("Africa/Lagos")
TELEGRAM_LIMIT_UTF16 = 4096
_SOURCE_HOSTS = {
    "BEA": {"apps.bea.gov", "www.bea.gov"},
    "Census": {"www.census.gov"},
    "BLS": {"www.bls.gov"},
    "DOL": {"www.dol.gov"},
    "Federal Reserve": {"www.federalreserve.gov"},
}
_SOURCE_ALIASES = {
    "U.S. Bureau of Economic Analysis": "BEA",
    "U.S. Census Bureau": "Census",
    "U.S. Bureau of Labor Statistics": "BLS",
    "U.S. Department of Labor": "DOL",
}
_FIELD_MAP = {
    "title": ("title", "title_verified"),
    "date": ("release_date_text", "date_verified"),
    "time": ("release_time_text", "time_verified"),
    "previous": ("previous_value", "previous_verified"),
    "forecast": ("forecast_value", "forecast_verified"),
    "actual": ("actual_value", "actual_verified"),
    "impact": ("provider_impact", "impact_verified"),
}
_FIELD_SOURCE_COLUMNS = {
    "title": "title_evidence_url",
    "date": "date_evidence_url",
    "time": "time_evidence_url",
    "previous": "previous_evidence_url",
    "forecast": "forecast_evidence_url",
    "actual": "actual_evidence_url",
    "impact": "impact_evidence_url",
}


class CalendarManagementError(ValueError):
    """A safe, user-displayable calendar-management validation error."""


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise CalendarManagementError("A timezone-aware timestamp is required.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _safe_evidence_url(source_name: str, value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname in _SOURCE_HOSTS.get(source_name, set())
        and parsed.username is None
        and parsed.password is None
    )


def _event_date(record: dict) -> date | None:
    event_at = record.get("event_at_utc")
    if isinstance(event_at, str) and (
        record.get("time_verified")
        or record.get("timezone_status") == "verified_explicit_utc_offset"
    ):
        try:
            parsed = datetime.fromisoformat(event_at.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(WAT).date()
        except ValueError:
            pass
    raw = str(record.get("release_date_text") or "").strip()
    range_match = re.fullmatch(
        r"([A-Za-z]+)\s+(\d{1,2})[–-](\d{1,2}),\s*(\d{4})", raw
    )
    if range_match:
        month_name, first, _last, year = range_match.groups()
        try:
            return date(
                int(year), datetime.strptime(month_name, "%B").month, int(first)
            )
        except ValueError:
            return None
    for pattern in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%a, %d %b %Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    return None


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


class OfficialCalendarManagementRepository:
    """Additive review/audit storage on the existing calendar SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        OfficialCalendarRepository(self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(usd_calendar_source_events)"
                ).fetchall()
            }
            additions = {
                "review_status": "TEXT NOT NULL DEFAULT 'held'",
                "entry_origin": "TEXT NOT NULL DEFAULT 'official_source'",
                "title_verified": "INTEGER NOT NULL DEFAULT 0",
                "date_verified": "INTEGER NOT NULL DEFAULT 0",
                "time_verified": "INTEGER NOT NULL DEFAULT 0",
                "previous_verified": "INTEGER NOT NULL DEFAULT 0",
                "forecast_verified": "INTEGER NOT NULL DEFAULT 0",
                "actual_verified": "INTEGER NOT NULL DEFAULT 0",
                "impact_verified": "INTEGER NOT NULL DEFAULT 0",
                "date_evidence_url": "TEXT",
                "title_evidence_url": "TEXT",
                "time_evidence_url": "TEXT",
                "previous_evidence_url": "TEXT",
                "forecast_evidence_url": "TEXT",
                "actual_evidence_url": "TEXT",
                "impact_evidence_url": "TEXT",
                "updated_at_utc": "TEXT",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE usd_calendar_source_events "
                        f"ADD COLUMN {name} {declaration}"
                    )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS usd_calendar_admin_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    field_name TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    evidence_url TEXT,
                    actor TEXT NOT NULL DEFAULT 'admin',
                    occurred_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_usd_calendar_audit_event
                    ON usd_calendar_admin_audit(external_id, audit_id);
                """
            )
            # Existing verified source rows retain their independent source-backed
            # date/time evidence; all other values remain unverified.
            connection.execute(
                """
                UPDATE usd_calendar_source_events
                SET title_verified=1
                WHERE entry_origin='official_source' AND title_verified=0
                """
            )
            connection.execute(
                """
                UPDATE usd_calendar_source_events
                SET date_verified=1
                WHERE verification_status IN (
                    'verified_schedule',
                    'date_time_listed_timezone_unverified',
                    'verified_meeting_window_release_time_unavailable'
                ) AND date_verified=0
                """
            )
            connection.execute(
                """
                UPDATE usd_calendar_source_events
                SET time_verified=1
                WHERE timezone_status='verified_explicit_utc_offset'
                    AND event_at_utc IS NOT NULL AND time_verified=0
                """
            )

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def list_records(
        self,
        filters: dict[str, str] | None = None,
        *,
        now: datetime | None = None,
    ) -> list[dict]:
        observed = now or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            raise ValueError("now must be timezone-aware.")
        rows = OfficialCalendarReadRepository(self.database_path).list_records()
        statuses = OfficialCalendarReadRepository(self.database_path).list_source_status()
        source_status = {str(row.get("source_name")): row for row in statuses}
        observed_utc = observed.astimezone(timezone.utc)
        for row in rows:
            review_status = str(row.get("review_status") or "held")
            retrieval = row.get("retrieved_at_utc")
            try:
                retrieved = datetime.fromisoformat(str(retrieval).replace("Z", "+00:00"))
                stale = (
                    retrieved.tzinfo is None
                    or observed_utc - retrieved.astimezone(timezone.utc)
                    < timedelta(0)
                    or observed_utc - retrieved.astimezone(timezone.utc)
                    > CALENDAR_STALE_AFTER
                )
            except (TypeError, ValueError):
                stale = True
            row["is_stale"] = stale
            source = str(row.get("source_name") or "")
            status_key = _SOURCE_ALIASES.get(source, source)
            if status_key in {"BLS", "DOL"} and status_key not in source_status:
                row["source_health"] = "UNAVAILABLE — SOURCE NOT VERIFIED"
            else:
                row["source_health"] = source_status.get(status_key, {}).get(
                    "status", "No source check recorded"
                )
            health = str(row["source_health"] or "").casefold()
            if review_status == "rejected":
                row["review_state"] = "rejected"
            elif review_status == "conflicting":
                row["review_state"] = "conflicting"
            elif stale:
                row["review_state"] = "stale"
            elif "unavailable" in health or "not verified" in health:
                row["review_state"] = "unavailable-source"
            elif review_status == "approved":
                row["review_state"] = "approved"
            else:
                row["review_state"] = "held"

        # Flag same-title/date records when independent sources disagree on
        # known timestamps or supplied figures; never pick a winner silently.
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            day = _event_date(row)
            title = " ".join(str(row.get("title") or "").casefold().split())
            if day and title:
                groups.setdefault((title, day.isoformat()), []).append(row)
        for group in groups.values():
            if len(group) < 2:
                continue
            for field in ("event_at_utc", "previous_value", "forecast_value", "actual_value"):
                known = {str(row.get(field)) for row in group if row.get(field) not in (None, "")}
                if len(known) > 1:
                    for row in group:
                        if row["review_state"] not in {"rejected", "stale"}:
                            row["review_state"] = "conflicting"
                    break

        filters = filters or {}
        for key, row_key in (
            ("event", "title"),
            ("source", "source_name"),
            ("impact", "provider_impact"),
            ("verification", "verification_status"),
        ):
            needle = str(filters.get(key) or "").strip().casefold()
            if needle:
                rows = [
                    row for row in rows
                    if needle in str(row.get(row_key) or "").casefold()
                ]
        date_filter = str(filters.get("date") or "").strip()
        if date_filter:
            rows = [
                row for row in rows
                if (
                    date_filter.casefold()
                    in str(row.get("release_date_text") or "").casefold()
                    or date_filter in str(_event_date(row) or "")
                )
            ]
        status_filter = str(filters.get("status") or "").strip().casefold()
        if status_filter:
            rows = [row for row in rows if row["review_state"] == status_filter]
        return rows

    def add_manual_record(
        self,
        *,
        source_name: str,
        title: str,
        release_date: str,
        release_time: str,
        source_url: str,
        now: datetime,
    ) -> str:
        source_name = source_name.strip()
        title = title.strip()
        release_date = release_date.strip()
        release_time = release_time.strip()
        source_url = source_url.strip()
        if source_name not in _SOURCE_HOSTS:
            raise CalendarManagementError(
                "Choose an official source: BEA, Census, BLS, DOL, or Federal Reserve."
            )
        if not title or len(title) > 180:
            raise CalendarManagementError("Event name must be 1–180 characters.")
        try:
            parsed_date = date.fromisoformat(release_date)
        except ValueError:
            raise CalendarManagementError("Date must use YYYY-MM-DD.") from None
        if release_time:
            try:
                parsed_time = datetime.fromisoformat(release_time.replace("Z", "+00:00"))
            except ValueError:
                raise CalendarManagementError(
                    "A time must be ISO 8601 and include an explicit UTC offset."
                ) from None
            if parsed_time.tzinfo is None:
                raise CalendarManagementError(
                    "A time must include an explicit UTC offset; no timezone is assumed."
                )
            if parsed_time.date() != parsed_date:
                raise CalendarManagementError(
                    "The timestamp date must match the event date."
                )
            event_at_utc = _utc_text(parsed_time)
            timezone_status = "manual_timezone_unverified"
        else:
            event_at_utc = None
            timezone_status = "unverified_no_timezone_in_source"
        if not _safe_evidence_url(source_name, source_url):
            raise CalendarManagementError(
                "Use an HTTPS link on the selected source’s official domain."
            )
        if now.tzinfo is None:
            raise CalendarManagementError("A timezone-aware current time is required.")
        external_id = "manual:" + hashlib.sha256(
            "|".join((source_name, title.casefold(), parsed_date.isoformat())).encode()
        ).hexdigest()[:24]
        with closing(self._connection()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO usd_calendar_source_events (
                    external_id, source_name, title, source_url, release_date_text,
                    release_time_text, event_at_utc, affected_instrument,
                    timezone_status, verification_status, retrieved_at_utc,
                    review_status, entry_origin, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'USD / XAUUSD', ?,
                          'manual_unverified', ?, 'held', 'manual', ?)
                """,
                (
                    external_id, source_name, title, source_url,
                    parsed_date.isoformat(), release_time or None, event_at_utc,
                    timezone_status, _utc_text(now), _utc_text(now),
                ),
            )
            inserted = connection.execute(
                "SELECT changes()"
            ).fetchone()[0] == 1
            if not inserted:
                existing = connection.execute(
                    "SELECT event_at_utc, review_status FROM usd_calendar_source_events "
                    "WHERE external_id=?",
                    (external_id,),
                ).fetchone()
                conflict = bool(
                    existing
                    and existing["event_at_utc"]
                    and event_at_utc
                    and existing["event_at_utc"] != event_at_utc
                )
                if conflict:
                    connection.execute(
                        "UPDATE usd_calendar_source_events SET review_status='conflicting', "
                        "updated_at_utc=? WHERE external_id=?",
                        (_utc_text(now), external_id),
                    )
                self._audit(
                    connection, external_id,
                    "manual_duplicate_conflict" if conflict else "manual_duplicate_ignored",
                    "release_time" if conflict else None,
                    str(existing["event_at_utc"]) if conflict else None,
                    event_at_utc if conflict else title,
                    source_url, now,
                )
            else:
                self._audit(
                    connection, external_id, "manual_add", None, None, title,
                    source_url, now,
                )
        return external_id

    def set_field(
        self,
        external_id: str,
        field: str,
        value: str,
        evidence_url: str,
        *,
        verified: bool,
        now: datetime,
    ) -> None:
        if field not in _FIELD_MAP:
            raise CalendarManagementError("That calendar field cannot be changed.")
        value = value.strip()
        evidence_url = evidence_url.strip()
        if not value or len(value) > 500:
            raise CalendarManagementError("Value must be 1–500 characters.")
        if now.tzinfo is None:
            raise CalendarManagementError("A timezone-aware current time is required.")
        with closing(self._connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM usd_calendar_source_events WHERE external_id=?",
                (external_id,),
            ).fetchone()
            if row is None:
                raise CalendarManagementError("That event no longer exists.")
            source_name = _SOURCE_ALIASES.get(
                str(row["source_name"]), str(row["source_name"])
            )
            if not _safe_evidence_url(source_name, evidence_url):
                raise CalendarManagementError(
                    "Evidence must be an HTTPS link on that source’s official domain."
                )
            column, verified_column = _FIELD_MAP[field]
            old_value = row[column]
            if field == "date":
                try:
                    value = date.fromisoformat(value).isoformat()
                except ValueError:
                    raise CalendarManagementError("Date must use YYYY-MM-DD.") from None
            elif field == "time":
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    raise CalendarManagementError(
                        "Time must be ISO 8601 with an explicit UTC offset."
                    ) from None
                if parsed.tzinfo is None:
                    raise CalendarManagementError(
                        "Time must include an explicit UTC offset; no timezone is assumed."
                    )
                try:
                    current_date = date.fromisoformat(str(row["release_date_text"]))
                except ValueError:
                    current_date = None
                if current_date is None:
                    raise CalendarManagementError(
                        "Verify an exact YYYY-MM-DD release date before adding a time."
                    )
                if parsed.date() != current_date:
                    raise CalendarManagementError(
                        "Time date must match the separately recorded event date."
                    )
                value = parsed.isoformat()
            elif field == "impact" and value.casefold() not in {
                "low", "medium", "high"
            }:
                raise CalendarManagementError(
                    "Impact must be Low, Medium, or High and needs its own evidence."
                )
            if field == "date":
                connection.execute(
                    "UPDATE usd_calendar_source_events SET release_date_text=?, "
                    "event_at_utc=NULL, release_time_text=NULL, time_verified=0, "
                    "time_evidence_url=NULL, date_verified=?, date_evidence_url=?, "
                    "review_status='held', updated_at_utc=? WHERE external_id=?",
                    (value, int(verified), evidence_url, _utc_text(now), external_id),
                )
            elif field == "time":
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                connection.execute(
                    "UPDATE usd_calendar_source_events SET release_time_text=?, "
                    "event_at_utc=?, timezone_status='verified_explicit_utc_offset', "
                    "time_verified=?, time_evidence_url=?, review_status='held', "
                    "updated_at_utc=? WHERE external_id=?",
                    (
                        value, _utc_text(parsed), int(verified), evidence_url,
                        _utc_text(now), external_id,
                    ),
                )
            else:
                evidence_column = _FIELD_SOURCE_COLUMNS.get(field)
                assignments = [f"{column}=?", "review_status='held'", "updated_at_utc=?"]
                values: list[object] = [value, _utc_text(now)]
                if verified_column:
                    assignments.append(f"{verified_column}=?")
                    values.append(int(verified))
                if evidence_column:
                    assignments.append(f"{evidence_column}=?")
                    values.append(evidence_url)
                values.append(external_id)
                connection.execute(
                    f"UPDATE usd_calendar_source_events SET {', '.join(assignments)} "
                    "WHERE external_id=?",
                    values,
                )
            self._audit(
                connection, external_id,
                "field_verified" if verified else "field_edited",
                field, None if old_value is None else str(old_value),
                value, evidence_url, now,
            )

    def set_review_status(
        self, external_id: str, status: str, *, now: datetime
    ) -> None:
        if status not in {"approved", "held", "rejected"}:
            raise CalendarManagementError("Unsupported review decision.")
        with closing(self._connection()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT review_status, date_verified, title_verified "
                "FROM usd_calendar_source_events WHERE external_id=?",
                (external_id,),
            ).fetchone()
            if row is None:
                raise CalendarManagementError("That event no longer exists.")
            if status == "approved" and not row["date_verified"]:
                raise CalendarManagementError(
                    "Verify the event date from its official source before approval."
                )
            if status == "approved" and not row["title_verified"]:
                raise CalendarManagementError(
                    "Verify the event title from its official source before approval."
                )
            old = str(row["review_status"])
            connection.execute(
                "UPDATE usd_calendar_source_events SET review_status=?, "
                "updated_at_utc=? WHERE external_id=?",
                (status, _utc_text(now), external_id),
            )
            self._audit(
                connection, external_id, f"review_{status}", "review_status",
                old, status, None, now,
            )

    def list_audit(self, external_id: str, *, limit: int = 20) -> list[dict]:
        with closing(self._connection()) as connection, connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM usd_calendar_admin_audit WHERE external_id=? "
                    "ORDER BY audit_id DESC LIMIT ?",
                    (external_id, min(max(limit, 1), 50)),
                ).fetchall()
            ]

    @staticmethod
    def reference_for(external_id: str) -> str:
        return hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:16]

    def resolve_reference(self, reference: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{16}", reference):
            raise CalendarManagementError("That calendar record link is invalid.")
        with closing(self._connection()) as connection:
            rows = connection.execute(
                "SELECT external_id FROM usd_calendar_source_events"
            ).fetchall()
        for row in rows:
            external_id = str(row["external_id"])
            if self.reference_for(external_id) == reference:
                return external_id
        raise CalendarManagementError("That calendar record no longer exists.")

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        external_id: str,
        action: str,
        field_name: str | None,
        old_value: str | None,
        new_value: str | None,
        evidence_url: str | None,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO usd_calendar_admin_audit (
                external_id, action, field_name, old_value, new_value,
                evidence_url, actor, occurred_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 'admin', ?)
            """,
            (
                external_id, action, field_name, old_value, new_value,
                evidence_url, _utc_text(now),
            ),
        )


def build_weekly_calendar_preview(
    records: list[dict],
    *,
    week_start: date,
    now: datetime | None = None,
    source_statuses: list[dict] | None = None,
) -> str:
    """Render admin-approved, fresh, independently date-verified events only."""
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    end_date = week_start + timedelta(days=7)
    eligible: list[tuple[date, dict]] = []
    for record in records:
        day = _event_date(record)
        if (
            record.get("review_status") == "approved"
            and record.get("title_verified")
            and record.get("date_verified")
            and day is not None
            and week_start <= day < end_date
            and not record.get("is_stale", True)
            and record.get("review_state") != "conflicting"
        ):
            eligible.append((day, record))
    eligible.sort(key=lambda pair: (pair[0], str(pair[1].get("title") or "")))
    lines = [
        "<b>ADMIN WEEKLY PREVIEW — NOT PUBLISHED</b>",
        "<b>USD &amp; GOLD — U.S. ECONOMIC RELEASES</b>",
        f"{week_start.strftime('%d %b')}–{(end_date - timedelta(days=1)).strftime('%d %b %Y')} · WAT",
        "",
    ]
    if not eligible:
        lines.extend(
            [
                "⚠️ <b>DATA-QUALITY WARNING</b>",
                "No events passed the current source, freshness, date-verification, "
                "and admin-review checks.",
                "This is not a complete economic calendar; unavailable coverage "
                "does not mean no events are scheduled.",
                "",
            ]
        )
    for day, record in eligible:
        title = html.escape(str(record.get("title") or "Unnamed event")[:160])
        source = html.escape(str(record.get("source_name") or "Official source")[:80])
        source_url = str(record.get("source_url") or "")
        parsed = urlparse(source_url)
        safe_url = (
            parsed.scheme == "https"
            and parsed.hostname in set().union(*_SOURCE_HOSTS.values())
        )
        lines.append(f"<b>{title}</b>")
        date_label = str(record.get("release_date_text") or day.strftime("%a, %d %b %Y"))
        event_at = record.get("event_at_utc")
        if record.get("time_verified") and event_at:
            try:
                parsed_event = datetime.fromisoformat(
                    str(event_at).replace("Z", "+00:00")
                )
                if parsed_event.tzinfo is not None:
                    date_label = parsed_event.astimezone(WAT).strftime(
                        "%a, %d %b %Y · %H:%M WAT"
                    )
            except ValueError:
                pass
        lines.append(f"📅 {date_label} · United States")
        if record.get("entry_origin") == "manual":
            lines.append(
                "Record origin: ADMIN-ENTERED — not automatically verified as an official event"
            )
        impact = record.get("provider_impact")
        if record.get("impact_verified") and impact:
            lines.append(f"Impact: {html.escape(str(impact))} (source verified)")
        elif impact:
            lines.append("Impact: Unavailable — provider-supplied, not independently verified")
        else:
            lines.append("Impact: Unavailable — not supplied by a verified source")
        for label, value_key, verified_key in (
            ("Previous", "previous_value", "previous_verified"),
            ("Forecast", "forecast_value", "forecast_verified"),
            ("Actual", "actual_value", "actual_verified"),
        ):
            value = record.get(value_key)
            display = (
                html.escape(str(value)[:100])
                if record.get(verified_key) and value not in (None, "")
                else "Unavailable — not independently verified"
            )
            lines.append(f"{label}: {display}")
        if safe_url:
            lines.append(
                f'Source: <a href="{html.escape(source_url, quote=True)}">{source}</a>'
            )
        else:
            lines.append(f"Source: {source} — verified source link unavailable")
        lines.append(
            "Possible relevance: This release may affect USD and gold through "
            "economic or rate expectations; the reaction is uncertain."
        )
        lines.append("")
    lines.extend(
        [
            "",
            "<b>SOURCE STATUS</b>",
        ]
    )
    by_source = {
        str(item.get("source_name")): item for item in (source_statuses or [])
    }
    for source in ("BEA", "Census", "Federal Reserve", "BLS", "DOL"):
        status = by_source.get(source)
        if status is None:
            label = (
                "UNAVAILABLE — SOURCE NOT VERIFIED"
                if source in {"BLS", "DOL"}
                else "No recent check recorded"
            )
        else:
            label = str(status.get("status") or "UNKNOWN")
            if status.get("failure_category"):
                label += f" ({status['failure_category']})"
        lines.append(f"{html.escape(source)}: {html.escape(label[:120])}")
    lines.extend(
        [
            "",
            "Market reactions can differ from initial expectations. This calendar "
            "is not an entry signal.",
            "<b>NO CONFIRMATION, NO ENTRY.</b>",
        ]
    )
    report = "\n".join(lines)
    if _utf16_length(report) > TELEGRAM_LIMIT_UTF16:
        raise CalendarManagementError(
            "Weekly preview exceeds Telegram’s message limit; narrow the week or event set."
        )
    return report


__all__ = [
    "CalendarManagementError",
    "OfficialCalendarManagementRepository",
    "build_weekly_calendar_preview",
]
