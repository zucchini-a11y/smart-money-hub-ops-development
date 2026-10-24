from __future__ import annotations

import json
import tempfile
import unittest
from html.parser import HTMLParser
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError

from smart_money_hub_bot.news_intelligence import (
    EconomicEvent,
    GeminiGoldImpactAnalyzer,
    NewsIntelligencePipeline,
    NewsRepository,
    NewsSourceError,
    SourceItem,
    VerifiedNewsItem,
    build_admin_news_alert,
    build_event_reminder,
    build_gold_impact_prompt,
    build_macro_section,
    build_release_alert,
    convert_event_to_wat,
    discover_gdelt_stories,
    fetch_bea_data,
    fetch_treasury_yields,
    is_stale,
    parse_rss_feed,
    sample_treasury_macro_alert,
    validate_gold_impact_analysis,
    verify_discovery_lead,
)
from smart_money_hub_bot.gemini_coach import GEMINI_MODEL


NOW = datetime(2026, 10, 24, 16, 15, tzinfo=timezone.utc)
OFFICIAL_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary2026.htm"
STORY_HEADLINE = "Federal Reserve publishes a monetary policy statement"


class _Response:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _size: int = -1) -> bytes:
        return self.body


def _source(
    *,
    headline: str = STORY_HEADLINE,
    summary: str = "The Federal Reserve published its scheduled policy statement.",
    url: str = OFFICIAL_URL,
    name: str = "Federal Reserve",
    published_at: datetime = NOW,
    retrieved_at: datetime = NOW,
    lead: bool = False,
    developing: bool = False,
) -> SourceItem:
    return SourceItem(
        headline=headline,
        summary=summary,
        source_name=name,
        source_url=url,
        published_at=published_at,
        retrieved_at=retrieved_at,
        tags=("usd",),
        source_item_id=url,
        is_discovery_lead=lead,
        developing=developing,
    )


class NewsIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db = Path(self.temp_dir.name) / "news.sqlite3"
        self.repository = NewsRepository(self.db)
        self.pipeline = NewsIntelligencePipeline(self.repository)

    def test_rss_parser_keeps_source_and_publication_timestamps(self) -> None:
        feed = b"""<?xml version="1.0"?>
        <rss><channel><item>
          <title>Fed statement &amp; release</title>
          <description>Official statement.</description>
          <link>https://www.federalreserve.gov/releases/statement.htm</link>
          <pubDate>Fri, 23 Oct 2026 14:30:00 -0400</pubDate>
          <guid>fed-123</guid>
        </item></channel></rss>"""
        parsed = parse_rss_feed(
            feed,
            source_name="Federal Reserve",
            source_url="https://www.federalreserve.gov/feeds/press_all.xml",
            retrieved_at=NOW,
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].headline, "Fed statement & release")
        self.assertEqual(parsed[0].published_at, datetime(2026, 10, 23, 18, 30, tzinfo=timezone.utc))
        self.assertEqual(parsed[0].retrieved_at, NOW)
        self.assertEqual(parsed[0].source_item_id, "fed-123")

    def test_rss_parser_rejects_untrusted_source_urls(self) -> None:
        with self.assertRaises(NewsSourceError) as caught:
            parse_rss_feed(
                b"<rss/>",
                source_name="Unknown",
                source_url="https://example.invalid/feed.xml",
            )
        self.assertEqual(caught.exception.category, "source_url_not_allowlisted")

    def test_gdelt_results_are_leads_and_need_official_verification(self) -> None:
        body = json.dumps(
            {
                "articles": [
                    {
                        "title": STORY_HEADLINE,
                        "url": "https://news.example/article",
                        "seendate": "20261024T150000Z",
                        "domain": "news.example",
                    }
                ]
            }
        ).encode()
        lead = discover_gdelt_stories(
            "Federal Reserve statement",
            start_date=date(2026, 10, 24),
            end_date=date(2026, 10, 24),
            retrieved_at=NOW,
            opener=lambda *_args, **_kwargs: _Response(body),
        )[0]
        self.assertTrue(lead.is_discovery_lead)
        self.assertEqual(
            verify_discovery_lead(lead, []).verification_status,
            "held",
        )

        verified = verify_discovery_lead(
            lead,
            [_source()],
        )
        self.assertEqual(verified.verification_status, "verified")
        self.assertTrue(verified.usable_for_gemini)
        self.assertIn("uncertain", verified.potential_gold_relevance)

    def test_mismatched_and_old_official_item_does_not_verify_lead(self) -> None:
        lead = _source(lead=True)
        evidence = _source(
            headline="A different economic topic",
            published_at=NOW.replace(year=2025),
        )
        result = verify_discovery_lead(lead, [evidence])
        self.assertEqual(result.verification_status, "held")
        self.assertFalse(result.usable_for_gemini)

    def test_same_story_is_deduplicated_and_changed_story_is_marked_updated(self) -> None:
        first = VerifiedNewsItem(
            item=_source(lead=True),
            verification_status="verified",
            evidence=(_source(),),
            verification_reason="official match",
        )
        saved = self.repository.save_news_item(first)
        duplicate = self.repository.save_news_item(first)
        self.assertEqual(saved["id"], duplicate["id"])
        self.assertEqual(duplicate["item_state"], "already_reported")

        revised = VerifiedNewsItem(
            item=_source(
                lead=True,
                summary="The Federal Reserve published a corrected policy statement.",
            ),
            verification_status="verified",
            evidence=(
                _source(summary="The official statement was corrected."),
            ),
            verification_reason="correction",
        )
        updated = self.repository.save_news_item(revised)
        self.assertEqual(saved["id"], updated["id"])
        self.assertEqual(updated["item_state"], "updated")
        developing = VerifiedNewsItem(
            item=_source(
                lead=True,
                summary="The official statement is still being updated.",
                developing=True,
            ),
            verification_status="verified",
            evidence=(_source(summary="The source says it is developing."),),
            verification_reason="developing coverage",
        )
        developing_row = self.repository.save_news_item(developing)
        self.assertEqual(developing_row["item_state"], "developing")
        self.assertEqual(len(self.repository.list_news_items()), 1)

    def test_pipeline_queues_verified_admin_alert_once_and_holds_unverified_lead(self) -> None:
        lead = _source(lead=True)
        held = self.pipeline.process_discovery_leads([lead], [])
        self.assertEqual(held[0]["verification_status"], "held")
        self.assertEqual(self.repository.list_pending_notifications(), [])

        verified = self.pipeline.process_discovery_leads([lead], [_source()])
        self.assertEqual(verified[0]["verification_status"], "verified")
        notifications = self.repository.list_pending_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["notification_type"], "verified_news")
        self.assertIn("Source:", notifications[0]["payload"])
        self.pipeline.process_discovery_leads([lead], [_source()])
        self.assertEqual(len(self.repository.list_pending_notifications()), 1)
        self.assertTrue(self.repository.mark_notification_sent(notifications[0]["id"]))

    def test_source_failure_notice_is_sanitized_and_deduplicated(self) -> None:
        error = NewsSourceError("rate_limit", 429)
        self.assertTrue(self.pipeline.record_source_failure("GDELT", error))
        self.assertFalse(self.pipeline.record_source_failure("GDELT", error))
        notice = self.repository.list_pending_notifications()[0]["payload"]
        self.assertIn("rate_limit", notice)
        self.assertNotIn("https://", notice)
        self.assertNotIn("key", notice.casefold())

    def test_http_quota_and_service_errors_are_classified_without_retry(self) -> None:
        for status, category in ((429, "rate_limit"), (503, "service_unavailable")):
            with self.subTest(status=status):
                calls = []

                def opener(request, timeout):
                    calls.append(request.full_url)
                    raise HTTPError(request.full_url, status, "provider text", {}, None)

                with self.assertRaises(NewsSourceError) as caught:
                    fetch_treasury_yields(2026, opener=opener)
                self.assertEqual(caught.exception.http_status, status)
                self.assertEqual(caught.exception.category, category)
                self.assertEqual(len(calls), 1)

    def test_event_values_remain_missing_and_changes_are_marked_revised(self) -> None:
        event = EconomicEvent(
            external_id="cpi-2026-11",
            title="CPI release",
            source_name="BLS",
            source_url="https://www.bls.gov/news.release/cpi.htm",
            event_at=datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc),
            source_timezone="America/New_York",
            previous=None,
            forecast=None,
            actual=None,
            retrieved_at=NOW,
        )
        stored = self.repository.save_event(event)
        self.assertIsNone(stored["previous_value"])
        self.assertIsNone(stored["forecast_value"])
        self.assertIsNone(stored["actual_value"])
        self.assertEqual(event.display_value("forecast"), "Unavailable")

        revised = EconomicEvent(
            **{
                **event.__dict__,
                "forecast": "3.1%",
                "retrieved_at": NOW,
            }
        )
        updated = self.repository.save_event(revised)
        self.assertEqual(updated["status"], "revised")

    def test_calendar_reminder_and_release_alert_require_correct_event_state(self) -> None:
        event = EconomicEvent(
            external_id="jobs-2026-11",
            title="Employment report & payrolls",
            source_name="BLS",
            source_url="https://www.bls.gov/news.release/empsit.htm",
            event_at=datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc),
            source_timezone="America/New_York",
            previous="150K",
            forecast=None,
            actual=None,
            status="scheduled",
            retrieved_at=NOW,
        )
        reminder = build_event_reminder(event)
        self.assertIn("14:30 WAT", reminder)
        self.assertIn("Forecast: Unavailable", reminder)
        self.assertIn("Actual: Unavailable", reminder)
        with self.assertRaises(ValueError):
            build_release_alert(event)

        released = EconomicEvent(
            **{
                **event.__dict__,
                "forecast": "150K",
                "actual": "175K",
                "status": "confirmed",
            }
        )
        alert = build_release_alert(released)
        self.assertIn("<b>175K</b>", alert)
        self.assertIn("Possible gold implications are uncertain", alert)

    def test_macro_section_uses_only_fresh_verified_sources(self) -> None:
        verified = VerifiedNewsItem(
            item=_source(lead=True),
            verification_status="verified",
            evidence=(_source(summary="Official policy statement was released."),),
        )
        held = VerifiedNewsItem(
            item=_source(headline="Unverified claim"),
            verification_status="held",
        )
        section = build_macro_section([verified, held], now=NOW)
        self.assertIn("Official policy statement", section)
        self.assertIn(OFFICIAL_URL, section)
        self.assertNotIn("Unverified claim", section)
        self.assertIn("uncertain", section)
        stale = VerifiedNewsItem(
            item=_source(retrieved_at=NOW.replace(day=23)),
            verification_status="verified",
            evidence=(_source(retrieved_at=NOW.replace(day=23)),),
        )
        self.assertIn(
            "No fresh, verified source items",
            build_macro_section([stale], now=NOW),
        )

    def test_timezone_conversion_handles_us_daylight_saving_change(self) -> None:
        before_fall_back = convert_event_to_wat(
            datetime(2026, 11, 1, 1, 30),
            "America/New_York",
        )
        after_fall_back = convert_event_to_wat(
            datetime(2026, 11, 1, 2, 30),
            "America/New_York",
        )
        self.assertEqual(before_fall_back.hour, 6)
        self.assertEqual(after_fall_back.hour, 8)
        self.assertEqual(before_fall_back.tzinfo.key, "Africa/Lagos")

    def test_staleness_holds_old_or_future_retrievals(self) -> None:
        self.assertFalse(is_stale(NOW, now=NOW, max_age=60))
        self.assertTrue(is_stale(NOW, now=NOW.replace(hour=18), max_age=60))
        self.assertTrue(
            is_stale(NOW.replace(day=25), now=NOW, max_age=60)
        )

    def test_unverified_items_are_not_sent_to_the_gold_analysis_prompt(self) -> None:
        verified = VerifiedNewsItem(
            item=_source(lead=True),
            verification_status="verified",
            evidence=(_source(),),
        )
        held = VerifiedNewsItem(
            item=_source(headline="Unverified rumor", lead=True),
            verification_status="held",
        )
        prompt = build_gold_impact_prompt([verified, held])
        self.assertIn(OFFICIAL_URL, prompt)
        self.assertNotIn("Unverified rumor", prompt)
        with self.assertRaises(ValueError):
            build_gold_impact_prompt([held])

    def test_analysis_validator_rejects_missing_citations_numbers_and_live_claims(self) -> None:
        item = VerifiedNewsItem(
            item=_source(lead=True),
            verification_status="verified",
            evidence=(
                _source(summary="The published release reported an observed value."),
            ),
        )
        sections = (
            "CONFIRMED FACTS\n"
            f"Official statement: {OFFICIAL_URL}\n\n"
            "EXPECTATIONS\nNot supplied.\n\n"
            "INTERPRETATION FOR XAU/USD\nPossible opposing effects; uncertain.\n\n"
            "UNKNOWN OR CONFLICTING\nNo forecast was supplied."
        )
        self.assertIsNone(validate_gold_impact_analysis(sections, [item]))
        self.assertEqual(
            validate_gold_impact_analysis(
                sections.replace("Possible opposing effects", "Gold is trading at 2345. "
                                 "Possible opposing effects"),
                [item],
            ),
            "unsupported_numeric_claim",
        )
        self.assertEqual(
            validate_gold_impact_analysis(
                sections.replace("Possible opposing effects", "Gold rose sharply. "
                                 "Possible opposing effects"),
                [item],
            ),
            "unsupported_live_market_claim",
        )
        self.assertEqual(
            validate_gold_impact_analysis(sections.replace(OFFICIAL_URL, ""), [item]),
            "source_citation_missing",
        )

    def test_admin_alert_and_sample_macro_alert_escape_html_and_show_source(self) -> None:
        verified = VerifiedNewsItem(
            item=_source(lead=True),
            verification_status="verified",
            evidence=(_source(summary="Official source: rate <statement> & details."),),
        )
        alert = build_admin_news_alert(verified)
        self.assertIn("rate &lt;statement&gt; &amp; details.", alert)
        self.assertIn("https://www.federalreserve.gov", alert)
        parser = HTMLParser()
        parser.feed(alert)
        parser.close()
        macro = sample_treasury_macro_alert(
            "2026-10-23",
            {"2y": "4.69", "10y": "5.00", "30y": "5.33"},
            {"2y": "4.65", "10y": "4.96"},
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
        )
        self.assertIn("4.69%", macro)
        self.assertIn("+0.04 percentage points", macro)
        self.assertIn("<a href=", macro)
        self.assertIn("they do not establish a direction", macro)

    def test_bea_api_requires_secret_without_exposing_it(self) -> None:
        with self.assertRaises(NewsSourceError) as caught:
            fetch_bea_data({"method": "GetData"}, api_key="")
        self.assertEqual(caught.exception.category, "bea_key_missing")

    def test_gemini_analyzer_uses_pinned_model_and_never_emits_unverified_data(self) -> None:
        item = VerifiedNewsItem(
            item=_source(lead=True),
            verification_status="verified",
            evidence=(
                _source(summary="The Fed published an official statement."),
            ),
        )
        answer = (
            "CONFIRMED FACTS\n"
            f"An official statement was published. {OFFICIAL_URL}\n\n"
            "EXPECTATIONS\nNo forecast was supplied.\n\n"
            "INTERPRETATION FOR XAU/USD\n"
            "The release may affect rate expectations; opposing effects are possible.\n\n"
            "UNKNOWN OR CONFLICTING\nNo live price or market reaction was provided."
        )

        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return _Response(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {"parts": [{"text": answer}]},
                            }
                        ]
                    }
                ).encode()
            )

        result = GeminiGoldImpactAnalyzer(
            "synthetic-secret",
            opener=opener,
        ).analyze([item])
        self.assertEqual(result, answer)
        self.assertTrue(captured["url"].endswith(f"/models/{GEMINI_MODEL}:generateContent"))
        self.assertEqual(captured["payload"]["generationConfig"]["maxOutputTokens"], 500)
        self.assertNotIn("synthetic-secret", captured["url"])
        self.assertNotIn("synthetic-secret", json.dumps(captured["payload"]))

    def test_gemini_rate_limit_fails_closed_without_alternate_model_retry(self) -> None:
        item = VerifiedNewsItem(
            item=_source(lead=True),
            verification_status="verified",
            evidence=(_source(),),
        )
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 429, "quota", {}, None)

        with self.assertRaises(NewsSourceError) as caught:
            GeminiGoldImpactAnalyzer("synthetic-secret", opener=opener).analyze([item])
        self.assertEqual(caught.exception.category, "gemini_rate_limit")
        self.assertEqual(caught.exception.http_status, 429)
        self.assertEqual(len(calls), 1)
        self.assertEqual(GeminiGoldImpactAnalyzer.model, GEMINI_MODEL)


if __name__ == "__main__":
    unittest.main()
