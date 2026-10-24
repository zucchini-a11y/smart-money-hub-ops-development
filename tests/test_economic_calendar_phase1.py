from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from smart_money_hub_bot.economic_calendar_phase1 import (
    OfficialCalendarRepository,
    build_calendar_phase_one_report,
    fetch_and_store_official_schedules,
    fetch_with_bounded_backoff,
    parse_bea_release_dates,
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


if __name__ == "__main__":
    unittest.main()
