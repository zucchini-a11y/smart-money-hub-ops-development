from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from xml.etree import ElementTree

from smart_money_hub_bot.economic_calendar_phase1 import (
    OfficialCalendarReadRepository,
    OfficialCalendarRepository,
    build_calendar_phase_one_report,
    fetch_and_store_official_schedules,
    fetch_with_bounded_backoff,
    format_calendar_admin_review,
    parse_bea_release_dates,
    parse_bls_release_ics,
    parse_census_retail_calendar,
)
from smart_money_hub_bot.news_intelligence import NewsRepository, NewsSourceError

NOW = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)


class Response:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size=-1) -> bytes:
        return self.body


class EconomicCalendarPhaseOneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "calendar.sqlite3"

    def test_bea_schedule_requires_explicit_offset_and_filters_to_usd_topics(self):
        payload = {
            "Gross Domestic Product": {
                "release_dates": [
                    "2026-10-29T12:30:00+00:00",
                    "2026-12-01T12:30:00",
                ]
            },
            "Personal Income and Outlays": {
                "release_dates": ["2026-10-30T12:30:00+00:00"]
            },
            "Corporate Profits": {
                "release_dates": ["2026-10-30T12:30:00+00:00"]
            },
        }
        records = parse_bea_release_dates(
            payload,
            retrieved_at=NOW,
            start_at=NOW,
            end_at=datetime(2026, 11, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            [record.title for record in records],
            ["Gross Domestic Product", "Personal Income and Outlays"],
        )
        self.assertEqual(records[0].event_at_wat.hour, 13)
        self.assertEqual(records[0].timezone_status, "verified_explicit_utc_offset")
        self.assertIsNone(records[0].forecast)
        self.assertIsNone(records[0].previous)
        self.assertIsNone(records[0].actual)
        self.assertIsNone(records[0].provider_impact)

    def test_bea_naive_timestamp_is_not_assumed_to_be_utc(self):
        records = parse_bea_release_dates(
            {"Gross Domestic Product": {"release_dates": ["2026-10-29T12:30:00"]}},
            retrieved_at=NOW,
            start_at=NOW,
            end_at=datetime(2026, 11, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(records, [])

    def test_bls_ics_verifies_only_cpi_ppi_and_employment_with_source_timezone(self):
        body = b"""BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Consumer Price Index
DTSTART;TZID=America/New_York:20261112T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Producer Price Index
DTSTART;TZID=America/New_York:20261113T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:The Employment Situation
DTSTART;TZID=America/New_York:20261106T083000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Productivity and Costs
DTSTART;TZID=America/New_York:20261105T083000
END:VEVENT
END:VCALENDAR
"""
        records = parse_bls_release_ics(
            body,
            retrieved_at=NOW,
            start_at=NOW,
            end_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(
            {record.title for record in records},
            {
                "Consumer Price Index (CPI)",
                "Producer Price Index (PPI)",
                "Employment Situation",
            },
        )
        cpi = next(record for record in records if "CPI" in record.title)
        self.assertEqual(cpi.event_at_utc, datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc))
        self.assertEqual(cpi.timezone_status, "verified_source_timezone:America/New_York")
        self.assertIn("TZID=America/New_York", cpi.release_time_text)
        self.assertEqual(cpi.source_name, "U.S. Bureau of Labor Statistics")
        self.assertEqual(cpi.source_url, "https://www.bls.gov/schedule/news_release/bls.ics")
        self.assertIsNone(cpi.forecast)
        self.assertIsNone(cpi.previous)
        self.assertIsNone(cpi.provider_impact)

    def test_bls_floating_event_time_is_not_converted_to_wat(self):
        body = b"""BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Consumer Price Index
DTSTART:20261210T083000
END:VEVENT
END:VCALENDAR
"""
        records = parse_bls_release_ics(
            body,
            retrieved_at=NOW,
            start_at=NOW,
            end_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0].event_at_utc)
        self.assertEqual(records[0].timezone_status, "unverified_missing_source_timezone")

    def test_census_retail_schedule_keeps_time_unconverted_without_timezone_evidence(self):
        page = b"""
        <table id="calendar">
          <tr><th>Indicator</th><th>Release Date</th><th>Time</th>
              <th>Period Covered</th></tr>
          <tr><td><a href="/retail/marts/www/">Advance Monthly Sales for Retail and Food Services</a></td>
              <td sorttable_customkey="202701150830">January 15, 2027</td>
              <td>8:30 AM</td><td>December 2026</td>
              <td class="hiden">A202701150830</td></tr>
          <tr><td><a href="/housing/">New Residential Construction</a></td>
              <td>January 20, 2027</td><td>8:30 AM</td><td>December 2026</td></tr>
        </table>
        """
        records = parse_census_retail_calendar(page, retrieved_at=NOW)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(
            record.title, "Advance Monthly Sales for Retail and Food Services"
        )
        self.assertEqual(record.release_time_text, "8:30 AM")
        self.assertIsNone(record.event_at_utc)
        self.assertEqual(
            record.verification_status, "date_time_listed_timezone_unverified"
        )
        self.assertEqual(
            record.source_url, "https://www.census.gov/retail/marts/www/"
        )

    def test_phase_one_preview_does_not_invent_wat_or_macro_values(self):
        record = {
            "title": "Advance Monthly Sales for Retail and Food Services",
            "release_date_text": "January 15, 2027",
            "release_time_text": "8:30 AM",
            "event_at_utc": None,
            "timezone_status": "unverified_no_timezone_in_source",
            "source_url": "https://www.census.gov/economic-indicators/calendar-listview.html",
        }
        preview = build_calendar_phase_one_report([record])
        self.assertIn("timezone unverified; no WAT conversion", preview)
        self.assertIn("Provider impact: Unavailable", preview)
        self.assertIn("Forecast: Unavailable", preview)
        self.assertIn("Actual: Unavailable", preview)
        self.assertIn("Phase 1 source preview — not published", preview)

    def test_backoff_retries_transient_errors_but_not_permission_errors(self):
        calls = []
        delays = []

        def transient():
            calls.append(1)
            if len(calls) < 3:
                raise NewsSourceError("service_unavailable", 503)
            return "ok"

        result = fetch_with_bounded_backoff(
            transient, sleep=delays.append, max_attempts=3
        )
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(delays, [1.0, 2.0])

        permission_calls = []

        def forbidden():
            permission_calls.append(1)
            raise NewsSourceError("permission_error", 403)

        with self.assertRaises(NewsSourceError):
            fetch_with_bounded_backoff(
                forbidden, sleep=delays.append, max_attempts=3
            )
        self.assertEqual(len(permission_calls), 1)

    def test_http_status_and_source_failures_are_persisted_and_queued_not_sent(self):
        bea = {
            "Gross Domestic Product": {
                "release_dates": ["2026-10-29T12:30:00+00:00"]
            }
        }
        census_html = b"""
        <table id="calendar"><tr><td><a href="/retail/">Advance Monthly Sales for Retail and Food Services</a></td>
        <td>January 15, 2027</td><td>8:30 AM</td><td>December 2026</td></tr></table>
        """

        def opener(request, timeout):
            url = request.full_url
            if "release_dates.json" in url:
                return Response(json.dumps(bea).encode())
            if "calendar-listview.html" in url:
                return Response(census_html)
            if "bls.gov" in url:
                raise HTTPError(url, 403, "blocked", {}, None)
            if "dol.gov" in url:
                raise HTTPError(url, 403, "blocked", {}, None)
            raise AssertionError("Unexpected official source request.")

        result = fetch_and_store_official_schedules(
            self.database, now=NOW, opener=opener, sleep=lambda _delay: None
        )
        self.assertEqual(result["BEA"], 1)
        self.assertEqual(result["Census"], 1)
        self.assertEqual(result["BLS"], "UNAVAILABLE — SOURCE NOT VERIFIED")
        self.assertEqual(result["DOL"], "UNAVAILABLE — SOURCE NOT VERIFIED")

        calendar_repo = OfficialCalendarRepository(self.database)
        rows = calendar_repo.list_records()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["source_name"] for row in rows},
            {"U.S. Bureau of Economic Analysis", "U.S. Census Bureau"},
        )
        statuses = {row["source_name"]: row for row in calendar_repo.list_source_status()}
        self.assertEqual(statuses["BLS"]["failure_category"], "permission_error")
        self.assertEqual(statuses["BLS"]["http_status"], 403)
        self.assertEqual(statuses["DOL"]["failure_category"], "permission_error")
        pending = NewsRepository(self.database).list_pending_notifications()
        self.assertEqual(len(pending), 2)
        self.assertTrue(all(row["notification_type"] == "calendar_source_unavailable" for row in pending))
        self.assertTrue(all(row["status"] == "pending" for row in pending))

    def test_admin_review_preserves_wat_evidence_missing_fields_and_source_failure(self):
        records = parse_bea_release_dates(
            {"Gross Domestic Product": {"release_dates": ["2026-10-29T12:30:00+00:00"]}},
            retrieved_at=NOW,
            start_at=NOW,
            end_at=datetime(2026, 11, 30, tzinfo=timezone.utc),
        )
        repository = OfficialCalendarRepository(self.database)
        repository.save_records(records)
        repository.record_source_status(
            "BLS",
            status="unavailable",
            checked_at=NOW,
            failure_category="permission_error",
            http_status=403,
        )
        review_repository = OfficialCalendarReadRepository(self.database)

        report, page_count = format_calendar_admin_review(
            review_repository.list_records(),
            review_repository.list_source_status(),
            now=NOW,
        )

        self.assertEqual(page_count, 1)
        self.assertIn("USD / XAUUSD", report)
        self.assertIn("2026-10-29T12:30:00+00:00", report)
        self.assertIn("WAT: Thu, 29 Oct 2026 13:30 WAT", report)
        self.assertIn("Forecast: UNAVAILABLE — not supplied", report)
        self.assertIn("Verification: verified_schedule", report)
        self.assertIn('href="https://www.bea.gov/news/schedule"', report)
        self.assertIn("BLS: unavailable", report)
        self.assertIn("HTTP 403", report)
        self.assertIn("DOL: UNAVAILABLE — SOURCE NOT VERIFIED", report)
        self.assertIn("Treasury observations are daily yields", report)

    def test_admin_review_does_not_convert_census_time_and_flags_stale_data(self):
        row = {
            "title": "Advance Monthly Sales & Services",
            "source_name": "U.S. Census Bureau",
            "affected_instrument": "USD / XAUUSD",
            "source_url": "https://www.census.gov/economic-indicators/calendar-listview.html",
            "release_date_text": "January 15, 2027",
            "release_time_text": "8:30 AM",
            "event_at_utc": None,
            "timezone_status": "unverified_no_timezone_in_source",
            "verification_status": "date_time_listed_timezone_unverified",
            "retrieved_at_utc": "2026-10-20T16:00:00+00:00",
            "previous_value": None,
            "forecast_value": None,
            "actual_value": None,
            "provider_impact": None,
        }

        report, _ = format_calendar_admin_review(
            [row],
            [],
            now=NOW,
        )

        self.assertIn("UNAVAILABLE — NOT VERIFIED; no WAT conversion", report)
        self.assertNotIn("WAT: Fri", report)
        self.assertIn("Freshness: STALE", report)
        self.assertIn("Advance Monthly Sales &amp; Services", report)
        self.assertIn("Forecast: UNAVAILABLE — not supplied", report)
        ElementTree.fromstring(f"<root>{report}</root>")

    def test_read_only_repository_survives_reopen_and_does_not_create_missing_database(self):
        records = parse_bea_release_dates(
            {"Gross Domestic Product": {"release_dates": ["2026-10-29T12:30:00+00:00"]}},
            retrieved_at=NOW,
            start_at=NOW,
            end_at=datetime(2026, 11, 30, tzinfo=timezone.utc),
        )
        writer = OfficialCalendarRepository(self.database)
        writer.save_records(records)
        writer.record_source_status("BEA", status="ok", checked_at=NOW)

        reopened = OfficialCalendarReadRepository(self.database)
        self.assertEqual(len(reopened.list_records()), 1)
        self.assertEqual(reopened.list_source_status()[0]["source_name"], "BEA")
        self.assertEqual(len(OfficialCalendarReadRepository(self.database).list_records()), 1)

        absent_path = Path(self.temp_dir.name) / "not-created.sqlite3"
        absent = OfficialCalendarReadRepository(absent_path)
        self.assertEqual(absent.list_records(), [])
        self.assertFalse(absent_path.exists())

    def test_admin_review_source_records_remain_deduplicated(self):
        records = parse_bea_release_dates(
            {"Gross Domestic Product": {"release_dates": ["2026-10-29T12:30:00+00:00"]}},
            retrieved_at=NOW,
            start_at=NOW,
            end_at=datetime(2026, 11, 30, tzinfo=timezone.utc),
        )
        repository = OfficialCalendarRepository(self.database)

        repository.save_records(records + records)

        reviewed = OfficialCalendarReadRepository(self.database).list_records()
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0]["external_id"], records[0].external_id)

    def test_admin_review_caps_unusually_long_fields_within_telegram_limit(self):
        oversized_url = "https://www.bea.gov/" + ("long-path-" * 100)
        rows = []
        for index in range(2):
            rows.append(
                {
                    "title": f"Event {index} " + ("🧠" * 300),
                    "source_name": "BEA",
                    "affected_instrument": "USD / XAUUSD",
                    "source_url": oversized_url,
                    "release_date_text": "2026-10-29",
                    "release_time_text": "12:30 UTC",
                    "event_at_utc": None,
                    "timezone_status": "unverified",
                    "verification_status": "unverified " * 100,
                    "retrieved_at_utc": NOW.isoformat(),
                    "previous_value": "📊" * 300,
                    "forecast_value": None,
                    "actual_value": None,
                    "provider_impact": None,
                }
            )

        report, page_count = format_calendar_admin_review(
            rows,
            [],
            now=NOW,
        )

        self.assertEqual(page_count, 1)
        self.assertLessEqual(len(report), 4096)
        self.assertLessEqual(len(report.encode("utf-16-le")) // 2, 4096)
        self.assertIn("Source link: unavailable or not allowlisted", report)
        self.assertNotIn(oversized_url, report)
        self.assertIn("Forecast: UNAVAILABLE — not supplied", report)
        self.assertIn("Actual: UNAVAILABLE — not supplied", report)
        ElementTree.fromstring(f"<root>{report}</root>")

    def test_calendar_review_pagination_includes_each_record_exactly_once(self):
        rows = [
            {
                "title": f"Unique event {index}",
                "source_name": "U.S. Bureau of Economic Analysis",
                "affected_instrument": "USD / XAUUSD",
                "source_url": "https://www.bea.gov/news/schedule",
                "release_date_text": f"2026-10-{25 + index:02d}",
                "release_time_text": "12:30:00+00:00",
                "event_at_utc": "2026-10-29T12:30:00+00:00",
                "timezone_status": "verified_explicit_utc_offset",
                "verification_status": "verified_schedule",
                "retrieved_at_utc": NOW.isoformat(),
                "previous_value": None,
                "forecast_value": None,
                "actual_value": None,
                "provider_impact": None,
            }
            for index in range(5)
        ]

        pages = []
        page_count = None
        for page in range(3):
            content, count = format_calendar_admin_review(
                rows,
                [],
                page=page,
                now=NOW,
            )
            pages.append(content)
            page_count = count

        combined = "\n".join(pages)
        self.assertEqual(page_count, 3)
        for index in range(5):
            self.assertEqual(combined.count(f"<b>Unique event {index}</b>"), 1)

    def test_existing_calendar_schema_is_migrated_without_losing_rows(self):
        import sqlite3

        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """
                CREATE TABLE usd_calendar_source_status (
                    source_name TEXT PRIMARY KEY, status TEXT NOT NULL,
                    failure_category TEXT, http_status INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0, checked_at_utc TEXT NOT NULL
                );
                CREATE TABLE usd_calendar_source_events (
                    external_id TEXT PRIMARY KEY, source_name TEXT NOT NULL,
                    title TEXT NOT NULL, source_url TEXT NOT NULL,
                    release_date_text TEXT NOT NULL, release_time_text TEXT,
                    event_at_utc TEXT, timezone_status TEXT NOT NULL,
                    previous_value TEXT, forecast_value TEXT, actual_value TEXT,
                    provider_impact TEXT, verification_status TEXT NOT NULL,
                    retrieved_at_utc TEXT NOT NULL
                );
                INSERT INTO usd_calendar_source_events VALUES (
                    'existing', 'U.S. Census Bureau', 'Retail sales',
                    'https://www.census.gov/', 'January 15, 2027', '8:30 AM',
                    NULL, 'unverified_no_timezone_in_source', NULL, NULL, NULL,
                    NULL, 'date_time_listed_timezone_unverified',
                    '2026-10-24T16:00:00+00:00'
                );
                """
            )

        migrated = OfficialCalendarRepository(self.database).list_records()

        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["external_id"], "existing")
        self.assertEqual(migrated[0]["affected_instrument"], "USD / XAUUSD")


if __name__ == "__main__":
    unittest.main()
