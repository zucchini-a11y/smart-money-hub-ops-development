from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from smart_money_hub_bot.economic_calendar_admin import (
    CalendarManagementError,
    OfficialCalendarManagementRepository,
    build_weekly_calendar_preview,
)
from smart_money_hub_bot.economic_calendar_phase1 import (
    OfficialCalendarReadRepository,
    OfficialCalendarRepository,
    format_calendar_admin_review,
    parse_bea_release_dates,
)

NOW = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)
BEA_URL = "https://www.bea.gov/news/schedule"


class EconomicCalendarAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "calendar.sqlite3"
        self.source = OfficialCalendarRepository(self.database)
        self.admin = OfficialCalendarManagementRepository(self.database)

    def _seed_bea(self, title: str = "Gross Domestic Product", *, day: int = 29):
        records = parse_bea_release_dates(
            {title: {"release_dates": [f"2026-10-{day:02}T12:30:00+00:00"]}},
            retrieved_at=NOW,
            start_at=NOW,
            end_at=NOW + timedelta(days=120),
        )
        self.source.save_records(records)
        self.source.record_source_status(
            "BEA", status="verified_schedule", checked_at=NOW, attempts=1
        )
        return records[0]

    def test_manual_records_are_deduplicated_and_isolated_from_source_pipeline(self):
        before = len(self.source.list_records())
        external_id = self.admin.add_manual_record(
            source_name="BEA",
            title="GDP release",
            release_date="2026-10-29",
            release_time="2026-10-29T12:30:00Z",
            source_url=BEA_URL,
            now=NOW,
        )
        duplicate_id = self.admin.add_manual_record(
            source_name="BEA",
            title="GDP release",
            release_date="2026-10-29",
            release_time="2026-10-29T12:30:00Z",
            source_url=BEA_URL,
            now=NOW,
        )
        self.assertEqual(external_id, duplicate_id)
        self.assertEqual(len(self.source.list_records()), before)
        rows = self.admin.list_records(now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_origin"], "manual")
        self.assertEqual(rows[0]["review_state"], "held")
        self.assertFalse(rows[0]["date_verified"])
        self.assertFalse(rows[0]["time_verified"])
        self.assertEqual(
            self.admin.list_audit(external_id)[0]["action"],
            "manual_duplicate_ignored",
        )

    def test_conflicting_manual_duplicate_is_held_and_audited(self):
        external_id = self.admin.add_manual_record(
            source_name="BEA", title="GDP release", release_date="2026-10-29",
            release_time="2026-10-29T12:30:00Z", source_url=BEA_URL, now=NOW,
        )
        self.admin.add_manual_record(
            source_name="BEA", title="GDP release", release_date="2026-10-29",
            release_time="2026-10-29T13:00:00Z", source_url=BEA_URL, now=NOW,
        )
        row = self.admin.list_records(now=NOW)[0]
        self.assertEqual(row["review_state"], "conflicting")
        self.assertEqual(self.admin.list_audit(external_id)[0]["action"],
                         "manual_duplicate_conflict")
        with self.assertRaises(CalendarManagementError):
            self.admin.set_review_status(external_id, "approved", now=NOW)

    def test_manual_entry_requires_source_link_and_never_assumes_timezone(self):
        with self.assertRaises(CalendarManagementError):
            self.admin.add_manual_record(
                source_name="BEA", title="GDP", release_date="2026-10-29",
                release_time="", source_url="https://example.com/event", now=NOW,
            )
        with self.assertRaises(CalendarManagementError):
            self.admin.add_manual_record(
                source_name="BEA", title="GDP", release_date="2026-10-29",
                release_time="2026-10-29T08:30:00", source_url=BEA_URL, now=NOW,
            )

    def test_field_verification_and_weekly_preview_use_only_verified_values(self):
        record = self._seed_bea()
        self.admin.set_review_status(record.external_id, "approved", now=NOW)
        self.admin.set_field(
            record.external_id, "actual", "4.1", BEA_URL, verified=True, now=NOW
        )
        self.admin.set_review_status(record.external_id, "approved", now=NOW)
        row = self.admin.list_records(now=NOW)[0]
        report = build_weekly_calendar_preview(
            [row],
            week_start=date(2026, 10, 26),
            now=NOW,
            source_statuses=[
                {"source_name": "BEA", "status": "verified_schedule"}
            ],
        )
        self.assertIn("Actual: 4.1", report)
        self.assertIn("13:30 WAT", report)
        self.assertIn("Previous: Unavailable", report)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", report)

        # A later edit is only an override in the private review table. It clears
        # field verification and does not modify the source-authoritative row.
        self.admin.set_field(
            record.external_id, "actual", "4.2", BEA_URL, verified=False, now=NOW
        )
        updated = self.admin.list_records(now=NOW)[0]
        self.assertFalse(updated["actual_verified"])
        self.assertIsNone(OfficialCalendarReadRepository(self.database).list_records()[0]["actual_value"])
        report = build_weekly_calendar_preview(
            [updated],
            week_start=date(2026, 10, 26),
            now=NOW,
            source_statuses=[
                {"source_name": "BEA", "status": "verified_schedule"}
            ],
        )
        self.assertIn("Actual: Unavailable", report)
        self.assertNotIn("Actual: 4.2", report)

    def test_manual_field_verification_is_separate_and_wat_is_not_assumed(self):
        external_id = self.admin.add_manual_record(
            source_name="BEA", title="GDP & income", release_date="2026-10-29",
            release_time="2026-10-29T12:30:00Z", source_url=BEA_URL, now=NOW,
        )
        self.admin.set_field(
            external_id, "title", "GDP & income", BEA_URL, verified=True, now=NOW
        )
        self.admin.set_field(
            external_id, "date", "2026-10-29", BEA_URL, verified=True, now=NOW
        )
        self.admin.set_review_status(external_id, "approved", now=NOW)
        row = self.admin.list_records(now=NOW)[0]
        self.assertFalse(row["time_verified"])
        preview = build_weekly_calendar_preview(
            [row], week_start=date(2026, 10, 26), now=NOW
        )
        self.assertIn("2026-10-29", preview)
        self.assertNotIn("13:30 WAT", preview)
        self.assertIn("ADMIN-ENTERED", preview)
        self.assertIn("GDP &amp; income", preview)

        self.admin.set_field(
            external_id,
            "time",
            "2026-10-29T12:30:00+00:00",
            BEA_URL,
            verified=True,
            now=NOW,
        )
        self.admin.set_review_status(external_id, "approved", now=NOW)
        row = self.admin.list_records(now=NOW)[0]
        preview = build_weekly_calendar_preview(
            [row], week_start=date(2026, 10, 26), now=NOW
        )
        self.assertIn("13:30 WAT", preview)

    def test_source_change_conflict_staleness_and_failure_block_preview(self):
        record = self._seed_bea()
        self.admin.set_review_status(record.external_id, "approved", now=NOW)
        changed = parse_bea_release_dates(
            {
                "GDP (revised label)": {
                    "release_dates": ["2026-10-29T12:30:00+00:00"]
                }
            },
            retrieved_at=NOW + timedelta(hours=1),
            start_at=NOW,
            end_at=NOW + timedelta(days=120),
        )
        # Same ID is not required for this test; a changed original source title
        # is a distinct event and the old reviewed item remains unchanged.
        self.source.save_records(changed)
        self.assertEqual(len(self.source.list_records()), 2)
        rows = self.admin.list_records(now=NOW + timedelta(days=2))
        self.assertTrue(all(row["review_state"] == "stale" for row in rows))
        preview = build_weekly_calendar_preview(
            rows,
            week_start=date(2026, 10, 26),
            now=NOW + timedelta(days=2),
            source_statuses=[
                {"source_name": "BEA", "status": "UNAVAILABLE — SOURCE NOT VERIFIED"}
            ],
        )
        self.assertIn("No events passed", preview)
        self.assertIn("BEA: UNAVAILABLE", preview)

    def test_source_update_to_same_event_marks_review_conflict(self):
        record = self._seed_bea()
        self.admin.set_review_status(record.external_id, "approved", now=NOW)
        changed = parse_bea_release_dates(
            {
                "Gross Domestic Product": {
                    "release_dates": ["2026-10-29T13:00:00+00:00"]
                }
            },
            retrieved_at=NOW + timedelta(hours=1),
            start_at=NOW,
            end_at=NOW + timedelta(days=120),
        )
        self.source.save_records(changed)
        row = self.admin.list_records(now=NOW + timedelta(hours=1))[0]
        self.assertEqual(row["review_state"], "conflicting")

    def test_pagination_has_no_missing_or_duplicate_review_records(self):
        for day in range(25, 30):
            self._seed_bea(f"Release {day}", day=day)
        records = self.admin.list_records(now=NOW)
        page_titles = []
        for page in range(3):
            text, page_count = format_calendar_admin_review(
                records,
                [{"source_name": "BEA", "status": "verified_schedule",
                  "checked_at_utc": NOW.isoformat()}],
                page=page,
                page_size=2,
                checked_at=NOW,
            )
            self.assertEqual(page_count, 3)
            page_titles.extend(
                title for title in (f"Release {day}" for day in range(25, 30))
                if f"<b>{title}</b>" in text
            )
        self.assertCountEqual(page_titles, [f"Release {day}" for day in range(25, 30)])
        self.assertEqual(len(page_titles), len(set(page_titles)))

    def test_review_overlay_and_audit_survive_repository_restart(self):
        record = self._seed_bea()
        self.admin.set_field(
            record.external_id, "forecast", "2.0", BEA_URL, verified=True, now=NOW
        )
        restarted = OfficialCalendarManagementRepository(self.database)
        row = next(
            item for item in restarted.list_records(now=NOW)
            if item["external_id"] == record.external_id
        )
        self.assertEqual(row["forecast_value"], "2.0")
        self.assertTrue(row["forecast_verified"])
        self.assertEqual(restarted.list_audit(record.external_id)[0]["action"],
                         "field_verified")
        columns = {
            row[1]
            for row in OfficialCalendarReadRepository(self.database)
            ._connection().__enter__().execute(
                "PRAGMA table_info(usd_calendar_source_events)"
            )
        }
        self.assertNotIn("review_status", columns)


if __name__ == "__main__":
    unittest.main()
