"""Admin-only management tools for the official USD/gold release calendar.

This module stores review decisions and field-level evidence. It is deliberately
not connected to the scheduler or any Telegram channel publisher.
"""

from __future__ import annotations

import hashlib
import html
import json
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS usd_calendar_admin_review_records (
                    external_id TEXT PRIMARY KEY,
                    review_status TEXT NOT NULL DEFAULT 'held',
                    entry_origin TEXT NOT NULL,
                    overrides_json TEXT NOT NULL DEFAULT '{}',
                    manual_data_json TEXT,
                    verified_fields_json TEXT NOT NULL DEFAULT '{}',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    base_fingerprint TEXT,
                    updated_at_utc TEXT NOT NULL
                );
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

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _fingerprint(record: dict) -> str:
        keys = (
            "source_name", "title", "source_url", "release_date_text",
            "release_time_text", "event_at_utc", "previous_value",
            "forecast_value", "actual_value", "provider_impact",
            "verification_status",
        )
        payload = {key: record.get(key) for key in keys}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _base_records(self) -> dict[str, dict]:
        return {
            str(row["external_id"]): row
            for row in OfficialCalendarReadRepository(self.database_path).list_records()
        }

    def _review_records(self) -> dict[str, dict]:
        with closing(self._connection()) as connection:
            return {
                str(row["external_id"]): dict(row)
                for row in connection.execute(
                    "SELECT * FROM usd_calendar_admin_review_records"
                ).fetchall()
            }

    @staticmethod
    def _json_object(value: object) -> dict:
        try:
            parsed = json.loads(str(value or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def list_records(
        self,
        filters: dict[str, str] | None = None,
        *,
        now: datetime | None = None,
    ) -> list[dict]:
        observed = now or datetime.now(timezone.utc)
        if observed.tzinfo is None:
            raise ValueError("now must be timezone-aware.")
        base_rows = self._base_records()
        overlays = self._review_records()
        source_status = {
            str(row.get("source_name")): row
            for row in OfficialCalendarReadRepository(self.database_path).list_source_status()
        }
        rows: list[dict] = []
        source_date_verification = {
            "verified_schedule",
            "date_time_listed_timezone_unverified",
            "verified_meeting_window_release_time_unavailable",
        }
        for external_id, base in base_rows.items():
            overlay = overlays.get(external_id)
            if overlay and overlay.get("entry_origin") == "manual":
                continue
            review_status = str((overlay or {}).get("review_status") or "held")
            verified_fields = {
                "title": True,
                "date": str(base.get("verification_status")) in source_date_verification,
                "time": (
                    str(base.get("timezone_status")) == "verified_explicit_utc_offset"
                    and bool(base.get("event_at_utc"))
                ),
                "previous": False,
                "forecast": False,
                "actual": False,
                "impact": False,
            }
            evidence: dict = {}
            conflict = False
            row = dict(base)
            if overlay:
                conflict = bool(
                    overlay.get("base_fingerprint")
                    and overlay["base_fingerprint"] != self._fingerprint(base)
                )
                if not conflict:
                    row.update(self._json_object(overlay.get("overrides_json")))
                verified_fields.update(
                    self._json_object(overlay.get("verified_fields_json"))
                )
                evidence.update(self._json_object(overlay.get("evidence_json")))
            if verified_fields.get("title"):
                evidence.setdefault("title", base.get("source_url"))
            if verified_fields.get("date"):
                evidence.setdefault("date", base.get("source_url"))
            if verified_fields.get("time"):
                evidence.setdefault("time", base.get("source_url"))
            rows.append(
                self._decorate_record(
                    row,
                    review_status=review_status,
                    entry_origin="official_source",
                    verified_fields=verified_fields,
                    evidence=evidence,
                    observed=observed,
                    source_status=source_status,
                    source_conflict=conflict,
                )
            )
        for external_id, overlay in overlays.items():
            if overlay.get("entry_origin") != "manual":
                continue
            manual_data = self._json_object(overlay.get("manual_data_json"))
            if not manual_data:
                continue
            rows.append(
                self._decorate_record(
                    manual_data,
                    review_status=str(overlay.get("review_status") or "held"),
                    entry_origin="manual",
                    verified_fields=self._json_object(
                        overlay.get("verified_fields_json")
                    ),
                    evidence=self._json_object(overlay.get("evidence_json")),
                    observed=observed,
                    source_status=source_status,
                    source_conflict=False,
                )
            )
        rows.sort(
            key=lambda row: (
                str(row.get("release_date_text") or ""),
                str(row.get("release_time_text") or ""),
                str(row.get("title") or ""),
            )
        )
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
        date_filter = str(filters.get("date") or "").strip().casefold()
        if date_filter:
            rows = [
                row for row in rows
                if date_filter in str(row.get("release_date_text") or "").casefold()
                or date_filter in str(_event_date(row) or "")
            ]
        status_filter = str(filters.get("status") or "").strip().casefold()
        if status_filter:
            rows = [row for row in rows if row.get("review_state") == status_filter]
        return rows

    @staticmethod
    def _decorate_record(
        row: dict,
        *,
        review_status: str,
        entry_origin: str,
        verified_fields: dict,
        evidence: dict,
        observed: datetime,
        source_status: dict[str, dict],
        source_conflict: bool,
    ) -> dict:
        result = dict(row)
        result["entry_origin"] = entry_origin
        result["review_status"] = review_status
        for field_name, column in (
            ("title", "title_verified"),
            ("date", "date_verified"),
            ("time", "time_verified"),
            ("previous", "previous_verified"),
            ("forecast", "forecast_verified"),
            ("actual", "actual_verified"),
            ("impact", "impact_verified"),
        ):
            result[column] = bool(verified_fields.get(field_name))
        for field_name, column in (
            ("title", "title_evidence_url"),
            ("date", "date_evidence_url"),
            ("time", "time_evidence_url"),
            ("previous", "previous_evidence_url"),
            ("forecast", "forecast_evidence_url"),
            ("actual", "actual_evidence_url"),
            ("impact", "impact_evidence_url"),
        ):
            result[column] = evidence.get(field_name)
        source = str(result.get("source_name") or "")
        key = _SOURCE_ALIASES.get(source, source)
        health_row = source_status.get(key)
        if health_row is None and key in {"BLS", "DOL"}:
            result["source_health"] = "UNAVAILABLE — SOURCE NOT VERIFIED"
        else:
            result["source_health"] = (
                (health_row or {}).get("status") or "No source check recorded"
            )
        retrieval = result.get("retrieved_at_utc")
        try:
            retrieved = datetime.fromisoformat(str(retrieval).replace("Z", "+00:00"))
            stale = (
                retrieved.tzinfo is None
                or observed.astimezone(timezone.utc)
                - retrieved.astimezone(timezone.utc) < timedelta(0)
                or observed.astimezone(timezone.utc)
                - retrieved.astimezone(timezone.utc) > CALENDAR_STALE_AFTER
            )
        except (TypeError, ValueError):
            stale = True
        result["is_stale"] = stale
        health = str(result["source_health"]).casefold()
        if review_status == "rejected":
            state = "rejected"
        elif source_conflict or review_status == "conflicting":
            state = "conflicting"
        elif stale:
            state = "stale"
        elif "unavailable" in health or "not verified" in health:
            state = "unavailable-source"
        elif review_status == "approved":
            state = "approved"
        else:
            state = "held"
        result["review_state"] = state
        return result

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
        manual_data = {
            "external_id": external_id,
            "source_name": source_name,
            "title": title,
            "source_url": source_url,
            "release_date_text": parsed_date.isoformat(),
            "release_time_text": release_time or None,
            "event_at_utc": event_at_utc,
            "affected_instrument": "USD / XAUUSD",
            "timezone_status": timezone_status,
            "previous_value": None,
            "forecast_value": None,
            "actual_value": None,
            "provider_impact": None,
            "verification_status": "manual_unverified",
            "retrieved_at_utc": _utc_text(now),
        }
        with closing(self._connection()) as connection, connection:
            existing = connection.execute(
                "SELECT * FROM usd_calendar_admin_review_records WHERE external_id=?",
                (external_id,),
            ).fetchone()
            if existing:
                existing_data = self._json_object(existing["manual_data_json"])
                conflict = bool(
                    existing_data.get("event_at_utc")
                    and event_at_utc
                    and existing_data["event_at_utc"] != event_at_utc
                )
                if conflict:
                    connection.execute(
                        "UPDATE usd_calendar_admin_review_records SET review_status='conflicting', "
                        "updated_at_utc=? WHERE external_id=?",
                        (_utc_text(now), external_id),
                    )
                self._audit(
                    connection, external_id,
                    "manual_duplicate_conflict" if conflict else "manual_duplicate_ignored",
                    "release_time" if conflict else None,
                    str(existing_data.get("event_at_utc")) if conflict else None,
                    event_at_utc if conflict else title,
                    source_url, now,
                )
            else:
                connection.execute(
                    """
                    INSERT INTO usd_calendar_admin_review_records (
                        external_id, review_status, entry_origin, manual_data_json,
                        verified_fields_json, evidence_json, updated_at_utc
                    ) VALUES (?, 'held', 'manual', ?, '{}', '{}', ?)
                    """,
                    (
                        external_id,
                        json.dumps(manual_data, ensure_ascii=False, sort_keys=True),
                        _utc_text(now),
                    ),
                )
                self._audit(
                    connection, external_id, "manual_add", None, None, title,
                    source_url, now,
                )
        return external_id

    @staticmethod
    def _source_verified_fields(record: dict) -> dict[str, bool]:
        return {
            "title": True,
            "date": str(record.get("verification_status"))
            in {
                "verified_schedule",
                "date_time_listed_timezone_unverified",
                "verified_meeting_window_release_time_unavailable",
            },
            "time": (
                str(record.get("timezone_status"))
                == "verified_explicit_utc_offset"
                and bool(record.get("event_at_utc"))
            ),
            "previous": False,
            "forecast": False,
            "actual": False,
            "impact": False,
        }

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
            overlay_row = connection.execute(
                "SELECT * FROM usd_calendar_admin_review_records WHERE external_id=?",
                (external_id,),
            ).fetchone()
            overlay = dict(overlay_row) if overlay_row else None
            if overlay and overlay["entry_origin"] == "manual":
                record = self._json_object(overlay.get("manual_data_json"))
                origin = "manual"
                overrides = {}
                baseline = None
                verified_fields = self._json_object(
                    overlay.get("verified_fields_json")
                )
                evidence = self._json_object(overlay.get("evidence_json"))
                source_conflict = False
            else:
                base_row = connection.execute(
                    "SELECT * FROM usd_calendar_source_events WHERE external_id=?",
                    (external_id,),
                ).fetchone()
                if base_row is None:
                    raise CalendarManagementError("That event no longer exists.")
                record = dict(base_row)
                origin = "official_source"
                current_fingerprint = self._fingerprint(record)
                source_conflict = bool(
                    overlay
                    and overlay.get("base_fingerprint")
                    and overlay["base_fingerprint"] != current_fingerprint
                )
                overrides = (
                    {}
                    if source_conflict or not overlay
                    else self._json_object(overlay.get("overrides_json"))
                )
                record.update(overrides)
                baseline = current_fingerprint
                verified_fields = self._source_verified_fields(dict(base_row))
                if overlay and not source_conflict:
                    verified_fields.update(
                        self._json_object(overlay.get("verified_fields_json"))
                    )
                evidence = (
                    {}
                    if source_conflict or not overlay
                    else self._json_object(overlay.get("evidence_json"))
                )
            source_name = _SOURCE_ALIASES.get(
                str(record.get("source_name")), str(record.get("source_name"))
            )
            if not _safe_evidence_url(source_name, evidence_url):
                raise CalendarManagementError(
                    "Evidence must be an HTTPS link on that source’s official domain."
                )
            column, verified_column = _FIELD_MAP[field]
            old_value = record.get(column)
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
                    current_date = date.fromisoformat(
                        str(record["release_date_text"])
                    )
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
                record.update(
                    release_date_text=value,
                    event_at_utc=None,
                    release_time_text=None,
                    timezone_status="unverified_no_timezone_in_source",
                )
                verified_fields["time"] = False
                evidence.pop("time", None)
            elif field == "time":
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                record.update(
                    release_time_text=value,
                    event_at_utc=_utc_text(parsed),
                    timezone_status=(
                        "verified_explicit_utc_offset"
                        if verified
                        else "manual_timezone_unverified"
                    ),
                )
            else:
                record[column] = value
            if field == "date":
                verified_fields["date"] = bool(verified)
            elif field == "time":
                verified_fields["time"] = bool(verified)
            else:
                verified_fields[field] = bool(verified)
            evidence[field] = evidence_url
            if origin == "manual":
                connection.execute(
                    """
                    UPDATE usd_calendar_admin_review_records
                    SET manual_data_json=?, review_status='held',
                        verified_fields_json=?, evidence_json=?, updated_at_utc=?
                    WHERE external_id=?
                    """,
                    (
                        json.dumps(record, ensure_ascii=False, sort_keys=True),
                        json.dumps(verified_fields, sort_keys=True),
                        json.dumps(evidence, sort_keys=True),
                        _utc_text(now),
                        external_id,
                    ),
                )
            else:
                if field == "date":
                    overrides.pop("event_at_utc", None)
                    overrides.pop("release_time_text", None)
                    overrides.pop("timezone_status", None)
                overrides[column] = record[column]
                if field == "time":
                    overrides.update(
                        event_at_utc=record["event_at_utc"],
                        timezone_status=record["timezone_status"],
                    )
                connection.execute(
                    """
                    INSERT INTO usd_calendar_admin_review_records (
                        external_id, review_status, entry_origin, overrides_json,
                        verified_fields_json, evidence_json, base_fingerprint,
                        updated_at_utc
                    ) VALUES (?, 'held', 'official_source', ?, ?, ?, ?, ?)
                    ON CONFLICT(external_id) DO UPDATE SET
                        review_status='held',
                        overrides_json=excluded.overrides_json,
                        verified_fields_json=excluded.verified_fields_json,
                        evidence_json=excluded.evidence_json,
                        base_fingerprint=excluded.base_fingerprint,
                        updated_at_utc=excluded.updated_at_utc
                    """,
                    (
                        external_id,
                        json.dumps(overrides, ensure_ascii=False, sort_keys=True),
                        json.dumps(verified_fields, sort_keys=True),
                        json.dumps(evidence, sort_keys=True),
                        baseline,
                        _utc_text(now),
                    ),
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
