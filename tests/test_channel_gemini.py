from __future__ import annotations

import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from smart_money_hub_bot.channel_gemini import (
    GeminiChannelContentService,
    GeminiChannelGenerationError,
)
from smart_money_hub_bot.gemini_coach import GEMINI_MODEL


class _Response:
    status = 200

    def __init__(self, payload: dict) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._data


def _candidate(text: str, finish_reason: str = "STOP") -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": text}],
                },
                "finishReason": finish_reason,
            }
        ]
    }


class GeminiChannelContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = GeminiChannelContentService("synthetic-test-key")

    def test_documented_candidate_parts_plain_text_are_parsed_using_only_pinned_model(
        self,
    ) -> None:
        captured = {}
        response_text = (
            "CATEGORY: education\nPOST:\n"
            "💧 SMART MONEY HUB | LIQUIDITY\n\n"
            "THE SWEEP IS NOT THE SIGNAL\n\n"
            "A sweep alone does not confirm a reversal.\n\n"
            "⚠️ REMEMBER\nNO CONFIRMATION, NO ENTRY."
        )

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(_candidate(response_text))

        with patch(
            "smart_money_hub_bot.channel_gemini.urlopen", side_effect=fake_urlopen
        ):
            draft = self.service.generate(
                schedule_date="2026-10-24",
                schedule_time="10:00",
                preferred_category="education",
                history=[{"content": "Prior post", "category": "education"}],
                admin_feedback=[],
            )

        request = captured["request"]
        self.assertTrue(request.full_url.endswith(f"/models/{GEMINI_MODEL}:generateContent"))
        self.assertEqual(captured["timeout"], 12)
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 700)
        self.assertNotIn("responseMimeType", payload["generationConfig"])
        self.assertNotIn("thinkingConfig", payload["generationConfig"])
        self.assertIn("Prior post", payload["contents"][0]["parts"][0]["text"])
        instruction = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("short, uppercase, category-specific title", instruction)
        self.assertIn("no Markdown or HTML", instruction)
        self.assertIn("use 💧 for liquidity lessons", instruction)
        self.assertIn("60–100 words", instruction)
        self.assertIn("exact brand text SMART MONEY HUB", instruction)
        self.assertIn("unapproved emoji before SMART MONEY HUB", instruction)
        self.assertIn("Do not state that institutions, banks, market makers", instruction)
        self.assertIn("price moves beyond a recognizable high or low", instruction)
        self.assertIn("orders naturally accumulate", instruction)
        self.assertIn("risk_management", instruction)
        self.assertIn("VERIFIED INFORMATION", instruction)
        self.assertIn("confident, ambitious, conversational community voice", instruction)
        self.assertIn("Do not copy the examples or claim profits", instruction)
        self.assertIn("recent published channel history", instruction)
        self.assertEqual(draft.category, "education")
        self.assertTrue(draft.content.startswith("💧 SMART MONEY HUB | LIQUIDITY"))

    def test_session_open_prompt_includes_brand_template_and_wat_context(self) -> None:
        captured = {}
        response_text = (
            "CATEGORY: new_week_preparation\nPOST:\n"
            "📊 SMART MONEY HUB | MARKET PREPARATION\n"
            "━━━━━━━━━━━━━━\n\n"
            "🇬🇧 LONDON SESSION OPEN\n\n"
            "Prepare your chart and define your plan before the session.\n\n"
            "🔍 WHAT TO PREPARE\n"
            "✅ Review context from your verified chart.\n\n"
            "🛡️ RISK REMINDER\n"
            "Set invalidation before considering a setup.\n\n"
            "⚠️ THE GOLDEN RULE\n"
            "NO CONFIRMATION, NO ENTRY."
        )

        def fake_urlopen(request, timeout):
            captured["request"] = request
            return _Response(_candidate(response_text))

        with patch(
            "smart_money_hub_bot.channel_gemini.urlopen", side_effect=fake_urlopen
        ):
            self.service.generate(
                schedule_date="2026-10-26",
                schedule_time="09:00",
                preferred_category="new_week_preparation",
                history=[],
                admin_feedback=[],
                session_context={
                    "session": "London",
                    "session_timezone": "Europe/London",
                    "session_local_open": "08:00",
                    "open_time_wat": "09:00 WAT",
                },
            )

        payload = json.loads(captured["request"].data.decode("utf-8"))
        instruction = payload["systemInstruction"]["parts"][0]["text"]
        user_context = payload["contents"][0]["parts"][0]["text"]
        self.assertIn("Follow this Smart Money Hub layout", instruction)
        self.assertIn("SESSION OPEN", instruction)
        self.assertIn("RISK REMINDER", instruction)
        self.assertIn("NO CONFIRMATION, NO ENTRY.", instruction)
        self.assertIn("making the topic, practical takeaways, and wording distinct", instruction)
        self.assertIn("do not reuse a recent main lesson", instruction)
        self.assertIn("do not assert", instruction.lower())
        self.assertIn("Do not include numerical opening times", instruction)
        self.assertIn("Europe/London", user_context)
        self.assertIn("09:00 WAT", user_context)

    def test_rejects_max_tokens_and_empty_candidate_text(self) -> None:
        for payload, expected in (
            (_candidate("CATEGORY: education\nPOST:\nshort", "MAX_TOKENS"), "gemini_max_tokens"),
            (_candidate(" \n ", "STOP"), "gemini_missing_text"),
        ):
            with self.subTest(expected=expected):
                with patch(
                    "smart_money_hub_bot.channel_gemini.urlopen",
                    return_value=_Response(payload),
                ):
                    with self.assertRaises(GeminiChannelGenerationError) as caught:
                        self.service.generate(
                            schedule_date="2026-10-24",
                            schedule_time="10:00",
                            preferred_category="education",
                            history=[],
                            admin_feedback=[],
                        )
                self.assertEqual(caught.exception.category, expected)

    def test_rate_limit_is_classified_without_model_failover(self) -> None:
        request_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent"
        )
        with patch(
            "smart_money_hub_bot.channel_gemini.urlopen",
            side_effect=HTTPError(request_url, 429, "quota", {}, None),
        ) as mocked:
            with self.assertRaises(GeminiChannelGenerationError) as caught:
                self.service.generate(
                    schedule_date="2026-10-24",
                    schedule_time="10:00",
                    preferred_category="education",
                    history=[],
                    admin_feedback=[],
                )

        self.assertEqual(caught.exception.category, "gemini_rate_limit")
        self.assertEqual(caught.exception.http_status, 429)
        self.assertEqual(mocked.call_count, 1)

    def test_missing_key_fails_closed_without_request(self) -> None:
        service = GeminiChannelContentService("")
        with patch("smart_money_hub_bot.channel_gemini.urlopen") as mocked:
            with self.assertRaises(GeminiChannelGenerationError) as caught:
                service.generate(
                    schedule_date="2026-10-24",
                    schedule_time="10:00",
                    preferred_category="education",
                    history=[],
                    admin_feedback=[],
                )
        self.assertEqual(caught.exception.category, "gemini_not_configured")
        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
