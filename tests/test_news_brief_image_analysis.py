from __future__ import annotations

import base64
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from smart_money_hub_bot.gemini_coach import GEMINI_MODEL
from smart_money_hub_bot.news_brief_image_analysis import (
    GeminiNewsImageAnalysisService,
    GeminiNewsImageError,
)


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def candidate(text: str, finish_reason: str = "STOP") -> dict:
    return {
        "candidates": [
            {
                "finishReason": finish_reason,
                "content": {"parts": [{"text": text}]},
            }
        ]
    }


class GeminiNewsImageAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.service = GeminiNewsImageAnalysisService("test-key")
        self.image = b"sample-image"
        self.evidence = [
            {
                "external_id": "bea:event-1",
                "source_name": "U.S. Bureau of Economic Analysis",
                "title": "Personal Income and Outlays",
                "release_date_text": "2026-10-29",
                "release_time_text": "08:30 AM ET",
                "event_at_utc": "2026-10-29T12:30:00+00:00",
                "timezone_status": "verified_explicit_utc_offset",
                "source_url": "https://www.bea.gov/release",
                "previous_value": None,
                "forecast_value": None,
                "actual_value": None,
            }
        ]

    @patch("smart_money_hub_bot.news_brief_image_analysis.urlopen")
    def test_uses_configured_model_and_inline_image_but_only_returns_allowed_ids(
        self, mocked_urlopen
    ):
        mocked_urlopen.return_value = FakeResponse(
            candidate(
                json.dumps(
                    {
                        "relevant_event_ids": [
                            "not-in-the-source-records",
                            "bea:event-1",
                            "bea:event-1",
                        ],
                        "visible_date_text": "Thursday",
                        "observed_events": [
                            {
                                "event_name": "Personal Income and Outlays",
                                "currency": "USD",
                                "time_text": "8:30 AM",
                                "impact_label": None,
                                "impact_marker": None,
                                "forecast_text": None,
                                "previous_text": None,
                                "actual_text": None,
                            }
                        ],
                    }
                )
            )
        )
        result = self.service.analyze(
            self.image,
            "image/jpeg",
            self.evidence,
        )
        self.assertEqual(result.relevant_event_ids, ("bea:event-1",))
        self.assertEqual(result.visible_date_text, "Thursday")
        self.assertEqual(len(result.observed_events), 1)
        self.assertEqual(
            result.observed_events[0].event_name,
            "Personal Income and Outlays",
        )
        request = mocked_urlopen.call_args.args[0]
        self.assertIn(GEMINI_MODEL, request.full_url)
        payload = json.loads(request.data)
        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "image/jpeg")
        self.assertEqual(
            base64.b64decode(parts[1]["inline_data"]["data"]),
            self.image,
        )
        prompt = parts[0]["text"]
        self.assertIn("untrusted input", prompt)
        self.assertIn("official records", prompt)
        self.assertIn("transcribe", prompt)
        self.assertIn("Do not infer an impact rating from a color or icon", prompt)
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 8192)

    @patch("smart_money_hub_bot.news_brief_image_analysis.urlopen")
    def test_rejects_unstructured_or_incomplete_model_response(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse(candidate("not json"))
        with self.assertRaises(GeminiNewsImageError):
            self.service.analyze(self.image, "image/jpeg", self.evidence)

    @patch("smart_money_hub_bot.news_brief_image_analysis.time.sleep")
    @patch("smart_money_hub_bot.news_brief_image_analysis.urlopen")
    def test_retries_one_transient_provider_failure(self, mocked_urlopen, mocked_sleep):
        mocked_urlopen.side_effect = [
            HTTPError("https://example.test", 503, "temporary", {}, None),
            FakeResponse(
                candidate(
                    json.dumps(
                        {
                            "visible_date_text": None,
                            "observed_events": [],
                            "relevant_event_ids": [],
                        }
                    )
                )
            ),
        ]

        result = self.service.analyze(self.image, "image/jpeg", self.evidence)

        self.assertEqual(result.observed_events, ())
        self.assertEqual(mocked_urlopen.call_count, 2)
        mocked_sleep.assert_called_once_with(0.5)

    def test_rejects_oversized_and_unsupported_images_without_request(self):
        with patch("smart_money_hub_bot.news_brief_image_analysis.urlopen") as mocked:
            with self.assertRaises(GeminiNewsImageError):
                self.service.analyze(b"x" * 4_000_001, "image/jpeg", self.evidence)
            with self.assertRaises(GeminiNewsImageError):
                self.service.analyze(self.image, "image/gif", self.evidence)
            mocked.assert_not_called()

    @patch("smart_money_hub_bot.news_brief_image_analysis.urlopen")
    def test_empty_evidence_still_transcribes_image_without_verified_matches(
        self, mocked_urlopen
    ):
        mocked_urlopen.return_value = FakeResponse(
            candidate(
                json.dumps(
                    {
                        "visible_date_text": None,
                        "observed_events": [
                            {
                                "event_name": "ADP Non-Farm Employment Change",
                                "currency": "USD",
                                "time_text": "2:15pm",
                                "impact_label": None,
                                "impact_marker": "yellow crown icon",
                                "forecast_text": None,
                                "previous_text": None,
                                "actual_text": None,
                            }
                        ],
                        "relevant_event_ids": [],
                    }
                )
            )
        )

        result = self.service.analyze(self.image, "image/jpeg", [])

        self.assertEqual(result.relevant_event_ids, ())
        self.assertEqual(
            result.observed_events[0].event_name,
            "ADP Non-Farm Employment Change",
        )
        self.assertEqual(result.observed_events[0].time_text, "2:15pm")
        self.assertEqual(result.observed_events[0].impact_label, None)
        self.assertEqual(
            result.observed_events[0].impact_marker,
            "yellow crown icon",
        )
        mocked_urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
