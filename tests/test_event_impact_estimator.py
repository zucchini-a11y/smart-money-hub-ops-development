from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from smart_money_hub_bot.event_impact_estimator import (
    GeminiEventImpactEstimator,
    event_impact_label,
)


class FakeResponse:
    status = 200

    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def official_events() -> list[dict]:
    return [
        {
            "external_id": "bea:gdp",
            "source_name": "U.S. Bureau of Economic Analysis",
            "title": "Gross Domestic Product",
            "release_date_text": "Thu, 05 Nov 2026",
            "event_at_utc": "2026-11-05T12:30:00+00:00",
            "verification_status": "verified_schedule",
        },
        {
            "external_id": "census:construction",
            "source_name": "U.S. Census Bureau",
            "title": "Construction Spending",
            "release_date_text": "November 5, 2026",
            "event_at_utc": None,
            "release_time_text": "10:00 AM",
            "verification_status": "date_time_listed_timezone_unverified",
        },
    ]


class GeminiEventImpactEstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "impact.sqlite3"

    def test_uses_only_verified_event_names_and_caches_labeled_estimates(self) -> None:
        calls: list[dict] = []

        def opener(request, *, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            prompt = payload["contents"][0]["parts"][0]["text"]
            events = json.loads(prompt)["events"]
            calls.append(payload)
            self.assertEqual(
                {event["source"] for event in events},
                {"U.S. Bureau of Economic Analysis", "U.S. Census Bureau"},
            )
            self.assertTrue(all("release_time_text" not in event for event in events))
            response = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "ratings": [
                                                {"id": events[0]["id"], "rating": "High"},
                                                {"id": events[1]["id"], "rating": "Low"},
                                            ]
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ]
            }
            return FakeResponse(response)

        estimator = GeminiEventImpactEstimator(
            self.database, "test-key", opener=opener
        )
        records = official_events()
        records.append({**records[0], "external_id": "bea:gdp-alias"})
        ratings = estimator.estimate(records)
        self.assertEqual(
            ratings,
            {
                "bea:gdp": "High",
                "bea:gdp-alias": "High",
                "census:construction": "Low",
            },
        )
        self.assertEqual(
            event_impact_label(records[0], ratings),
            "🔺 Impact: High (Gemini estimate; not official)",
        )
        self.assertEqual(estimator.estimate(records), ratings)
        self.assertEqual(len(calls), 1)
        restarted_estimator = GeminiEventImpactEstimator(
            self.database,
            "test-key",
            opener=lambda *_args, **_kwargs: self.fail(
                "a cached impact estimate should survive estimator restart"
            ),
        )
        self.assertEqual(restarted_estimator.estimate(records), ratings)
        prompt = calls[0]["systemInstruction"]["parts"][0]["text"]
        self.assertIn("not official ratings", prompt)
        self.assertIn("Do not predict bullish or bearish direction", prompt)

    def test_ignores_unverified_sources_and_provider_response_ids(self) -> None:
        calls = 0

        def opener(request, *, timeout):
            nonlocal calls
            calls += 1
            prompt = json.loads(request.data.decode("utf-8"))["contents"][0]["parts"][0]["text"]
            events = json.loads(prompt)["events"]
            self.assertEqual(len(events), 2)
            self.assertNotIn("bls:unverified", {event["id"] for event in events})
            response = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "ratings": [
                                                {"id": "unknown-id", "rating": "High"},
                                                {"id": events[0]["id"], "rating": "Low"},
                                                {"id": events[1]["id"], "rating": "Invented"},
                                            ]
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ]
            }
            return FakeResponse(response)

        records = official_events() + [
            {
                "external_id": "bls:unverified",
                "source_name": "U.S. Bureau of Labor Statistics",
                "title": "Employment Situation",
                "release_date_text": "2026-11-06",
                "event_at_utc": "2026-11-06T13:30:00+00:00",
                "verification_status": "UNAVAILABLE — SOURCE NOT VERIFIED",
            }
        ]
        ratings = GeminiEventImpactEstimator(
            self.database, "test-key", opener=opener
        ).estimate(records)
        self.assertEqual(ratings, {"bea:gdp": "Low"})
        self.assertEqual(calls, 1)

    def test_duplicate_conflicting_model_ratings_are_not_selected(self) -> None:
        def opener(request, *, timeout):
            prompt = json.loads(request.data.decode("utf-8"))["contents"][0]["parts"][0]["text"]
            event_id = json.loads(prompt)["events"][0]["id"]
            response = {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "ratings": [
                                                {"id": event_id, "rating": "High"},
                                                {"id": event_id, "rating": "Low"},
                                            ]
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ]
            }
            return FakeResponse(response)

        rating = GeminiEventImpactEstimator(
            self.database, "test-key", opener=opener
        ).estimate(official_events()[:1])
        self.assertEqual(rating, {})

    def test_failed_model_response_leaves_estimate_unavailable(self) -> None:
        def opener(request, *, timeout):
            return FakeResponse({"candidates": [{"finishReason": "MAX_TOKENS"}]})

        self.assertEqual(
            GeminiEventImpactEstimator(
                self.database, "test-key", opener=opener
            ).estimate(official_events()),
            {},
        )
        self.assertEqual(
            event_impact_label(official_events()[0], None),
            "🔺 Impact: Unavailable (Gemini estimate not available)",
        )

    def test_verified_official_rating_takes_precedence_over_estimate(self) -> None:
        record = {
            "external_id": "bea:pce",
            "provider_impact": "High",
            "verification_status": "verified_schedule",
        }
        self.assertEqual(
            event_impact_label(record, {"bea:pce": "Low"}),
            "🔺 Impact: High (official source)",
        )


if __name__ == "__main__":
    unittest.main()
