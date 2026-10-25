from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from email.message import Message
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from smart_money_hub_bot.finance_calendar_prototype import (
    API_OVERVIEW_URL,
    FinanceCalendarError,
    FinanceCalendarPrototypeClient,
    FreshnessPolicy,
    OfficialScheduleEvidence,
    _get_bytes,
    build_source_comparison_report,
    evaluate_provider_records,
    parse_bea_schedule,
    parse_bls_release_ics,
    parse_census_release_calendar,
    parse_fed_fomc_calendar,
    render_weekly_preview,
)

NOW = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)
BEA_EVENT_AT = datetime(2026, 10, 29, 12, 30, tzinfo=timezone.utc)
ATTRIBUTION = {
    "source": "financecalendar.com",
    "terms": "Free for any use with attribution: link to https://www.financecalendar.com",
}


class FakeResponse:
    status = 200
    headers = {}

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size=-1) -> bytes:
        return self.body


def provider_event(**overrides):
    event = {
        "id": "bea-gdp-2026-10-29",
        "source_id": "bea",
        "series_code": "us-gdp",
        "series_name": "US Gross Domestic Product",
        "title": "US Gross Domestic Product October 2026",
        "country": "US",
        "date": "2026-10-29",
        "release_at_utc": BEA_EVENT_AT.isoformat(),
        "release_tz": "America/New_York",
        "time_precision": "minute",
        "status": "confirmed",
        "impact": "high",
        "prior": None,
        "consensus": None,
        "actual": None,
        "source_name": "Bureau of Economic Analysis",
        "source_url": "https://www.bea.gov/news/schedule",
        "source_license": None,
        "source_rights": None,
        "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        "last_verified_at": (NOW - timedelta(minutes=5)).isoformat(),
        "data_stale": False,
        "release_stage": "advance",
    }
    event.update(overrides)
    return event


def provider_status(**overrides):
    status = {
        "ok": True,
        "snapshot": {
            "generated_at": (NOW - timedelta(minutes=10)).isoformat(),
            "age_seconds": 600,
        },
        "source_health": [
            {
                "source_id": "bea",
                "status": "success",
                "checked_at": (NOW - timedelta(minutes=6)).isoformat(),
                "fetched_at": (NOW - timedelta(minutes=6)).isoformat(),
            }
        ],
    }
    status.update(overrides)
    return status


def official_gdp(**overrides):
    evidence = {
        "series_code": "us-gdp",
        "event_date": date(2026, 10, 29),
        "source_name": "U.S. Bureau of Economic Analysis",
        "source_url": "https://apps.bea.gov/API/signup/release_dates.json",
        "retrieved_at": NOW,
        "release_at_utc": BEA_EVENT_AT,
        "source_timezone": "UTC",
    }
    evidence.update(overrides)
    return OfficialScheduleEvidence(**evidence)


def evaluate(
    events,
    *,
    status=None,
    evidence=None,
    now=NOW,
    failures=None,
    freshness_policy=None,
):
    return evaluate_provider_records(
        {"events": events, "attribution": ATTRIBUTION},
        status or provider_status(),
        evidence if evidence is not None else [official_gdp()],
        now=now,
        source_failures=failures,
        **(
            {"freshness_policy": freshness_policy}
            if freshness_policy is not None
            else {}
        ),
    )


class FinanceCalendarPrototypeTests(unittest.TestCase):
    def test_api_client_is_limited_to_us_and_a_92_day_read_only_window(self):
        captured = []

        def opener(request, timeout):
            captured.append(request.full_url)
            return FakeResponse(b'{"events":[],"attribution":{}}')

        client = FinanceCalendarPrototypeClient(opener=opener, sleep=lambda _: None)
        client.get_calendar(date(2026, 10, 25), date(2026, 11, 25))
        self.assertIn("country=US", captured[0])
        self.assertIn("limit=500", captured[0])
        self.assertIn("format=json", captured[0])
        self.assertIn("financecalendar.com", API_OVERVIEW_URL)
        with self.assertRaises(ValueError):
            client.get_calendar(date(2026, 1, 1), date(2026, 4, 4))

    def test_rate_limit_retry_after_is_respected_and_recovers(self):
        attempts = []
        delays = []

        def opener(request, timeout):
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise HTTPError(
                    request.full_url,
                    429,
                    "Too Many Requests",
                    {"Retry-After": "3"},
                    None,
                )
            return FakeResponse(b'{"ok":true}')

        body, _headers = _get_bytes(
            "https://www.financecalendar.com/wp-json/fc/v1/status",
            opener=opener,
            sleep=delays.append,
            now=NOW,
        )
        self.assertEqual(json.loads(body), {"ok": True})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(delays, [3.0])

    def test_retry_after_over_bound_fails_without_sleeping(self):
        delays = []

        def opener(request, timeout):
            raise HTTPError(
                request.full_url, 429, "Too Many Requests", {"Retry-After": "60"}, None
            )

        with self.assertRaises(FinanceCalendarError) as raised:
            _get_bytes(
                "https://www.financecalendar.com/wp-json/fc/v1/status",
                opener=opener,
                sleep=delays.append,
                now=NOW,
            )
        self.assertEqual(raised.exception.category, "retry_after_exceeds_bound")
        self.assertEqual(raised.exception.http_status, 429)
        self.assertEqual(delays, [])

    def test_transient_service_error_retries_once_and_recovers(self):
        attempts = []
        delays = []

        def opener(request, timeout):
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 503, "Unavailable", {}, None)
            return FakeResponse(b'{"ok":true}')

        body, _headers = _get_bytes(
            "https://www.financecalendar.com/wp-json/fc/v1/status",
            opener=opener,
            sleep=delays.append,
            now=NOW,
        )
        self.assertEqual(json.loads(body), {"ok": True})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(delays, [1.0])

    def test_permission_failure_is_sanitized_and_not_retried(self):
        attempts = []

        def opener(request, timeout):
            attempts.append(request.full_url)
            raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

        with self.assertRaises(FinanceCalendarError) as raised:
            _get_bytes(
                "https://www.bls.gov/schedule/news_release/bls.ics",
                opener=opener,
                sleep=lambda _: self.fail("403 should not retry"),
                now=NOW,
            )
        self.assertEqual(raised.exception.category, "permission_error")
        self.assertEqual(raised.exception.http_status, 403)
        self.assertEqual(len(attempts), 1)

    def test_http_200_and_provider_verified_flags_do_not_replace_official_match(self):
        event = provider_event()
        result = evaluate([event])
        self.assertEqual(result.verified_count, 1)
        self.assertEqual(
            result.candidates[0].verification_status, "verified_date_and_time"
        )
        self.assertEqual(result.candidates[0].wat_time.hour, 13)
        self.assertEqual(result.candidates[0].wat_time.minute, 30)
        self.assertEqual(result.candidates[0].reason, "official_date_time_match")

        no_official_check = evaluate([event], evidence=[])
        self.assertEqual(
            no_official_check.candidates[0].verification_status, "held"
        )
        self.assertEqual(
            no_official_check.candidates[0].reason, "official_source_not_verified"
        )

    def test_provider_wide_degraded_health_is_reported_but_source_health_is_checked(self):
        status = provider_status(ok=False)
        result = evaluate([provider_event()], status=status)
        self.assertEqual(result.provider_health_status, "degraded")
        self.assertEqual(result.verified_count, 1)
        report = build_source_comparison_report(result, generated_at=NOW)
        self.assertIn("Provider health: degraded", report)
        self.assertIn("provider-source-health=success", report)

        bad_source = provider_status(
            ok=False,
            source_health=[
                {
                    "source_id": "bea",
                    "status": "degraded",
                    "checked_at": (NOW - timedelta(minutes=6)).isoformat(),
                    "fetched_at": (NOW - timedelta(minutes=6)).isoformat(),
                }
            ],
        )
        held = evaluate([provider_event()], status=bad_source)
        self.assertEqual(held.candidates[0].reason, "provider_source_health_not_success")

        stale_source = provider_status(
            source_health=[
                {
                    "source_id": "bea",
                    "status": "success",
                    "checked_at": (NOW - timedelta(hours=25)).isoformat(),
                    "fetched_at": (NOW - timedelta(hours=25)).isoformat(),
                }
            ]
        )
        held = evaluate([provider_event()], status=stale_source)
        self.assertEqual(
            held.candidates[0].reason, "provider_source_health_stale_or_unknown"
        )

    def test_stale_snapshot_record_and_failed_official_check_are_held(self):
        stale_snapshot = provider_status(
            snapshot={
                "generated_at": (NOW - timedelta(hours=25)).isoformat(),
                "age_seconds": 90_000,
            }
        )
        result = evaluate([provider_event()], status=stale_snapshot)
        self.assertEqual(
            result.candidates[0].reason,
            "provider_snapshot_stale_or_unverifiable",
        )

        stale_record = provider_event(
            last_verified_at=(NOW - timedelta(hours=25)).isoformat()
        )
        result = evaluate([stale_record])
        self.assertEqual(
            result.candidates[0].reason, "record_verification_stale"
        )

        result = evaluate(
            [provider_event()],
            evidence=[],
            failures={"BEA": "permission_error_403"},
        )
        self.assertEqual(result.candidates[0].verification_status, "held")
        report = build_source_comparison_report(result, generated_at=NOW)
        self.assertIn("OFFICIAL SOURCE CHECK FAILED: BEA: permission_error_403", report)

    def test_snapshot_age_mismatch_is_held_even_when_provider_reports_freshness(self):
        status = provider_status(
            snapshot={
                "generated_at": (NOW - timedelta(hours=8)).isoformat(),
                "age_seconds": 60,
            }
        )
        result = evaluate([provider_event()], status=status)
        self.assertEqual(result.snapshot_freshness_status, "age_mismatch")
        self.assertEqual(
            result.candidates[0].reason, "provider_snapshot_age_mismatch"
        )
        preview = render_weekly_preview(
            result, week_start=date(2026, 10, 26), week_end=date(2026, 11, 1)
        )
        self.assertIn("age_mismatch", preview)
        self.assertIn("No events passed both the freshness", preview)
        self.assertNotIn("Gross Domestic Product release", preview)

    def test_source_health_uses_its_six_hour_limit(self):
        status = provider_status(
            source_health=[
                {
                    "source_id": "bea",
                    "status": "success",
                    "checked_at": (NOW - timedelta(hours=7)).isoformat(),
                    "fetched_at": (NOW - timedelta(hours=7)).isoformat(),
                }
            ]
        )
        result = evaluate([provider_event()], status=status)
        self.assertEqual(
            result.candidates[0].reason, "provider_source_health_stale_or_unknown"
        )

    def test_record_freshness_is_source_specific_and_configurable(self):
        event = provider_event(
            series_code="us-cpi",
            source_id="bls",
            source_name="U.S. Bureau of Labor Statistics",
            source_url="https://www.bls.gov/schedule/news_release/bls.ics",
            last_verified_at=(NOW - timedelta(hours=13)).isoformat(),
        )
        status = provider_status(
            source_health=[
                {
                    "source_id": "bls",
                    "status": "success",
                    "checked_at": (NOW - timedelta(minutes=5)).isoformat(),
                    "fetched_at": (NOW - timedelta(minutes=5)).isoformat(),
                }
            ]
        )
        result = evaluate([event], status=status, evidence=[])
        self.assertEqual(
            result.candidates[0].reason, "record_verification_stale"
        )

        stricter = FreshnessPolicy(
            record_verification={"bea": timedelta(hours=2)}
        )
        event = provider_event(last_verified_at=(NOW - timedelta(hours=3)).isoformat())
        result = evaluate([event], freshness_policy=stricter)
        self.assertEqual(
            result.candidates[0].reason, "record_verification_stale"
        )

    def test_future_record_update_and_missing_timestamps_are_not_fresh(self):
        event = provider_event(updated_at=(NOW + timedelta(minutes=1)).isoformat())
        result = evaluate([event])
        self.assertEqual(
            result.candidates[0].reason, "provider_record_updated_at_in_future"
        )

        status = provider_status(
            snapshot={"generated_at": (NOW - timedelta(minutes=5)).isoformat()}
        )
        result = evaluate([provider_event()], status=status)
        self.assertEqual(
            result.candidates[0].reason,
            "provider_snapshot_stale_or_unverifiable",
        )

    def test_official_evidence_has_an_independent_freshness_limit(self):
        evidence = official_gdp(retrieved_at=NOW - timedelta(hours=25))
        result = evaluate([provider_event()], evidence=[evidence])
        self.assertEqual(result.candidates[0].verification_status, "held")
        self.assertEqual(result.candidates[0].reason, "official_evidence_stale")

    def test_figure_fields_are_verified_independently_from_the_schedule(self):
        event = provider_event(prior="2.0%", consensus="2.1%", actual="1.5%")
        evidence = official_gdp(
            verified_fields=frozenset({"previous", "actual"}),
            previous_value="2.0%",
            actual_value="1.5%",
        )
        result = evaluate([event], evidence=[evidence])
        candidate = result.candidates[0]
        self.assertEqual(candidate.verification_status, "verified_date_and_time")
        self.assertEqual(candidate.field_verification["previous"], "verified")
        self.assertEqual(candidate.field_verification["forecast"], "present_unverified")
        self.assertEqual(candidate.field_verification["actual"], "verified")
        self.assertEqual(candidate.verified_values["actual"], "1.5%")

        mismatched = official_gdp(
            verified_fields=frozenset({"actual"}),
            actual_value="1.4%",
        )
        result = evaluate([event], evidence=[mismatched])
        candidate = result.candidates[0]
        self.assertEqual(candidate.verification_status, "conflict")
        self.assertEqual(candidate.reason, "official_value_mismatch")
        self.assertEqual(candidate.field_conflicts, ["actual"])
        report = build_source_comparison_report(result, generated_at=NOW)
        self.assertIn("Conflicting records:", report)
        self.assertIn("official_figure_value_conflict", report)

    def test_official_value_can_be_shown_without_a_provider_value(self):
        evidence = official_gdp(
            verified_fields=frozenset({"previous"}),
            previous_value="2.0%",
        )
        result = evaluate([provider_event()], evidence=[evidence])
        candidate = result.candidates[0]
        self.assertEqual(candidate.field_verification["previous"], "verified")
        self.assertEqual(candidate.verified_values["previous"], "2.0%")

    def test_event_time_conflict_is_flagged_and_not_selected(self):
        wrong_time = official_gdp(
            release_at_utc=datetime(2026, 10, 29, 13, 30, tzinfo=timezone.utc)
        )
        result = evaluate([provider_event()], evidence=[wrong_time])
        self.assertEqual(result.candidates[0].verification_status, "conflict")
        self.assertEqual(result.candidates[0].reason, "official_time_mismatch")
        self.assertIsNone(result.candidates[0].wat_time)

    def test_official_date_conflict_requires_same_reference_period(self):
        event = provider_event(period="September 2026")
        wrong_date = official_gdp(
            event_date=date(2026, 10, 30), reference_period="September 2026"
        )
        result = evaluate([event], evidence=[wrong_date])
        self.assertEqual(result.candidates[0].verification_status, "conflict")
        self.assertEqual(result.candidates[0].reason, "official_date_mismatch")

        unrelated_period = official_gdp(
            event_date=date(2026, 10, 30), reference_period="August 2026"
        )
        result = evaluate([event], evidence=[unrelated_period])
        self.assertEqual(result.candidates[0].verification_status, "held")
        self.assertEqual(result.candidates[0].reason, "official_source_not_verified")

    def test_exact_duplicates_collapse_but_disagreeing_values_are_conflicts(self):
        event = provider_event()
        result = evaluate([event, dict(event)])
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.verified_count, 1)

        disagreement = provider_event(impact="medium")
        result = evaluate([event, disagreement])
        self.assertEqual(result.conflicts[0]["category"], "duplicate_provider_records_conflict")
        self.assertEqual(result.candidates, [])

    def test_non_allowlisted_and_ism_records_are_excluded(self):
        result = evaluate(
            [
                provider_event(series_code="us-ism-manufacturing-pmi"),
                provider_event(series_code="us-treasury-bills"),
                provider_event(country="GB"),
            ]
        )
        self.assertEqual(result.excluded_count, 3)
        self.assertEqual(result.candidates, [])

    def test_missing_values_rights_and_attribution_are_explicit_in_preview(self):
        event = provider_event(
            prior="2.0%",
            consensus="2.1%",
            title="GDP <estimate & outlook>",
            observations=[
                {
                    "source_rights": {
                        "attribution": "Source <official publisher>",
                        "policy": "Retain source credit",
                    }
                }
            ]
        )
        result = evaluate([event])
        candidate = result.candidates[0]
        self.assertEqual(candidate.source_rights_status, "supplied")
        self.assertIn("Source <official publisher>", str(candidate.source_rights_notice))
        preview = render_weekly_preview(
            result, week_start=date(2026, 10, 26), week_end=date(2026, 11, 1)
        )
        self.assertIn("Calendar data: <a href=\"https://www.financecalendar.com\">Finance Calendar</a>", preview)
        self.assertIn("Previous: Unavailable", preview)
        self.assertIn("Forecast/consensus: Unavailable", preview)
        self.assertIn("Actual: Unavailable.", preview)
        self.assertIn("Source rights notice:", preview)
        self.assertIn("13:30 WAT", preview)
        self.assertIn("Gross Domestic Product release", preview)
        self.assertNotIn("GDP &lt;estimate", preview)
        self.assertIn("Source &lt;official publisher&gt;", preview)
        self.assertIn("Previous: Unavailable", preview)
        comparison = build_source_comparison_report(result, generated_at=NOW)
        self.assertIn("previous=present_unverified; value_withheld", comparison)
        self.assertIn("forecast=present_unverified; value_withheld", comparison)
        self.assertIn("Generated at: 2026-10-25T03:00:00+00:00", preview)
        self.assertIn("not a complete U.S. economic calendar", preview)

    def test_unreviewed_source_license_holds_event(self):
        result = evaluate([provider_event(source_license={"license": "restricted"})])
        self.assertEqual(result.candidates[0].verification_status, "held")
        self.assertEqual(
            result.candidates[0].reason, "record_source_license_review_required"
        )

    def test_fed_date_only_evidence_does_not_create_a_wat_time(self):
        event = provider_event(
            series_code="fomc",
            source_id="fed",
            source_name="Federal Reserve",
            source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            date="2026-10-28",
            release_at_utc="2026-10-28T18:00:00+00:00",
        )
        status = provider_status(
            source_health=[
                {
                    "source_id": "fed",
                    "status": "success",
                    "checked_at": (NOW - timedelta(minutes=6)).isoformat(),
                    "fetched_at": (NOW - timedelta(minutes=6)).isoformat(),
                }
            ]
        )
        fed_evidence = OfficialScheduleEvidence(
            series_code="fomc",
            event_date=date(2026, 10, 28),
            source_name="Board of Governors of the Federal Reserve System",
            source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            retrieved_at=NOW,
        )
        result = evaluate([event], status=status, evidence=[fed_evidence])
        self.assertEqual(
            result.candidates[0].verification_status, "verified_date_only"
        )
        self.assertIsNone(result.candidates[0].wat_time)

    def test_dst_aware_bls_ics_parser_preserves_source_timezone_and_converts_to_wat(self):
        ics = b"""BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Employment Situation
DTSTART;TZID=America/New_York:20261106T083000
END:VEVENT
END:VCALENDAR
"""
        rows = parse_bls_release_ics(ics, retrieved_at=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].series_code, "us-nfp")
        self.assertEqual(rows[0].source_timezone, "America/New_York")
        self.assertEqual(rows[0].release_at_utc.hour, 13)
        self.assertEqual(rows[0].release_at_utc.minute, 30)
        self.assertEqual(
            rows[0].release_at_utc.astimezone(ZoneInfo("Africa/Lagos")).hour, 14
        )

    def test_official_parsers_only_accept_explicit_times_and_matching_scope(self):
        bea = parse_bea_schedule(
            {
                "Gross Domestic Product": {
                    "release_dates": ["2026-10-29T12:30:00+00:00", "2026-10-30T12:30"]
                },
                "Personal Income and Outlays": {
                    "release_dates": ["2026-10-29T12:30:00Z"]
                },
                "Corporate Profits": {
                    "release_dates": ["2026-10-29T12:30:00+00:00"]
                },
            },
            retrieved_at=NOW,
        )
        self.assertEqual([item.series_code for item in bea], ["us-gdp", "us-pce"])
        self.assertTrue(all(item.release_at_utc.tzinfo for item in bea))

        fed_body = (
            b"<h3>2026 FOMC Meetings</h3><p>October 27-28</p>"
            b"<h3>2025 FOMC Meetings</h3>"
        )
        fed = parse_fed_fomc_calendar(fed_body, retrieved_at=NOW)
        self.assertEqual([item.event_date for item in fed], [date(2026, 10, 28)])
        self.assertIsNone(fed[0].release_at_utc)

        census_body = b"""<table id="calendar">
        <tr><td>Advance Monthly Sales for Retail and Food Services</td>
        <td>October 30, 2026</td><td>8:30 AM</td></tr>
        </table>"""
        census = parse_census_release_calendar(census_body, retrieved_at=NOW)
        self.assertEqual(census[0].series_code, "us-retail-sales")
        self.assertIsNone(census[0].release_at_utc)
        self.assertEqual(census[0].release_time_text, "8:30 AM")
        self.assertIsNone(census[0].source_timezone)


if __name__ == "__main__":
    unittest.main()
