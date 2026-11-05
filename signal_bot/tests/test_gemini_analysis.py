import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from PIL import Image

from smh.gemini_analysis import (
    GeminiAnalysisError,
    analyze_chart_with_gemini,
)


class FakeResponse:
    def __init__(self, payload):
        payloads = payload if isinstance(payload, list) else [payload]
        self.payload = b"".join(
            b"data: " + json.dumps(item).encode("utf-8") + b"\n\n"
            for item in payloads
        ) + b"data: [DONE]\n\n"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def readline(self, limit=-1):
        if not self.payload:
            return b""
        end = self.payload.find(b"\n")
        end = len(self.payload) if end < 0 else end + 1
        if limit >= 0:
            end = min(end, limit)
        line, self.payload = self.payload[:end], self.payload[end:]
        return line


class GeminiAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.image_path = Path(self.temp_dir.name) / "chart.png"
        Image.new("RGB", (24, 16), "#345678").save(self.image_path, format="PNG")
        self.analysis = (
            "📍 MARKET: XAUUSD\n"
            "⏱️ TIMEFRAME: M15\n\n"
            "🎯 KEY AREAS OF INTEREST:\n\n"
            "🩷 POI ZONE: 4,124.00 – 4,132.00\n"
            "➖ REFERENCE LEVEL: 4,113.30\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🔎 WHAT WE’RE WATCHING:\n\n"
            "Price reaction around your marked POI and surrounding market structure.\n\n"
            "We need to observe:\n"
            "💧 Liquidity behaviour\n"
            "📉 Displacement\n"
            "🔄 CHoCH / BOS\n"
            "📊 FVG formation\n"
            "🎯 Retest and entry confirmation\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🚦 CONFIRMATION STATUS:\n\n"
            "⚠️ Confirmation has not yet been established.\n\n"
            "❌ NO CONFIRMATION, NO ENTRY.\n\n"
            "Do not enter simply because price reaches the POI. Wait for the required "
            "confirmation before considering a trade.\n\n"
            "🛡️ Protect your capital and manage your risk responsibly.\n\n"
            "SMART MONEY HUB\n"
            "Learn • Confirm • Execute • Grow 🎯"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sends_inline_image_and_note_with_key_in_header(self):
        opener = Mock(return_value=FakeResponse({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis}]},
            }]
        }))
        result = analyze_chart_with_gemini(
            self.image_path, "Watch for a close above my marked area.",
            api_key="test-key-never-logged", opener=opener,
            model="gemini-3.8-flash",
        )

        self.assertEqual(result, self.analysis)
        request = opener.call_args.args[0]
        self.assertTrue(
            request.full_url.endswith(
                "/models/gemini-3.8-flash:streamGenerateContent?alt=sse"))
        self.assertEqual(request.get_header("Accept"), "text/event-stream")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key-never-logged")
        self.assertNotIn("test-key-never-logged", request.full_url)
        body = json.loads(request.data)
        self.assertEqual(
            body["generationConfig"]["thinkingConfig"]["thinkingLevel"], "low")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 1024)
        self.assertEqual(opener.call_args.kwargs["timeout"], 15)
        parts = body["contents"][0]["parts"]
        self.assertIn("Watch for a close above my marked area.", parts[0]["text"])
        self.assertIn("H1 bias/structure", parts[0]["text"])
        self.assertIn("clearly marked area is THEIR POI", parts[0]["text"])
        self.assertIn("A POI touch or liquidity sweep alone is not entry confirmation", parts[0]["text"])
        self.assertIn("never estimate or copy sample values", parts[0]["text"])
        self.assertIn("NO CONFIRMATION, NO ENTRY", parts[0]["text"])
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "image/png")
        self.assertEqual(
            base64.b64decode(parts[1]["inline_data"]["data"]),
            self.image_path.read_bytes(),
        )

    def test_verified_responsive_model_is_the_default(self):
        opener = Mock(return_value=FakeResponse({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis}]},
            }]
        }))
        analyze_chart_with_gemini(
            self.image_path, api_key="test-key", opener=opener,
        )
        request = opener.call_args.args[0]
        self.assertTrue(
            request.full_url.endswith(
                "/models/gemini-3.5-flash:streamGenerateContent?alt=sse"))

    def test_large_chart_is_downscaled_for_gemini_without_changing_original(self):
        large_path = Path(self.temp_dir.name) / "large-chart.jpg"
        noise = Image.effect_noise((3000, 2200), 35).convert("RGB")
        noise.save(large_path, format="JPEG", quality=95)
        original_bytes = large_path.read_bytes()
        opener = Mock(return_value=FakeResponse({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis}]},
            }]
        }))

        analyze_chart_with_gemini(
            large_path, api_key="test-key", opener=opener,
            model="gemini-3.8-flash",
        )

        sent_image = json.loads(opener.call_args.args[0].data)["contents"][0]["parts"][1]
        payload = base64.b64decode(sent_image["inline_data"]["data"])
        with Image.open(io.BytesIO(payload)) as processed:
            self.assertEqual(processed.format, "JPEG")
            self.assertLessEqual(max(processed.size), 2048)
        self.assertEqual(large_path.read_bytes(), original_bytes)

    def test_streamed_text_chunks_are_combined_before_validation(self):
        split = len(self.analysis) // 2
        opener = Mock(return_value=FakeResponse([
            {"candidates": [{"content": {"parts": [{"text": self.analysis[:split]}]}}]},
            {"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis[split:]}]},
            }]},
        ]))
        result = analyze_chart_with_gemini(
            self.image_path, api_key="test-key", opener=opener,
            model="gemini-3.8-flash",
        )
        self.assertEqual(result, self.analysis)

    def test_missing_api_key_fails_explicitly(self):
        with self.assertRaisesRegex(GeminiAnalysisError, "GEMINI_API_KEY"):
            analyze_chart_with_gemini(self.image_path, api_key="")

    def test_timeout_explains_google_did_not_respond_and_is_not_retried(self):
        opener = Mock(side_effect=TimeoutError("read timed out"))
        with self.assertLogs("smh.gemini_analysis", level="WARNING") as captured:
            with self.assertRaisesRegex(
                    GeminiAnalysisError, "Google Gemini did not respond within 15 seconds"):
                analyze_chart_with_gemini(
                    self.image_path, api_key="test-key", opener=opener)
        self.assertEqual(opener.call_count, 1)
        self.assertIn("category=TIMEOUT", "\n".join(captured.output))
        self.assertIn("elapsed_seconds=", "\n".join(captured.output))

    def test_trade_instruction_output_is_rejected(self):
        opener = Mock(return_value=FakeResponse({
            "candidates": [{"content": {"parts": [{"text": "BUY NOW at 2500"}]}}]
        }))
        with self.assertRaisesRegex(GeminiAnalysisError, "safety check"):
            analyze_chart_with_gemini(self.image_path, api_key="test-key", opener=opener)

    def test_incomplete_analysis_is_rejected(self):
        opener = Mock(return_value=FakeResponse({
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{
                    "text": "📍 MARKET: XAUUSD\n🩷 POI ZONE: Blue box"
                }]},
            }]
        }))
        with self.assertRaisesRegex(GeminiAnalysisError, "incomplete chart review"):
            analyze_chart_with_gemini(self.image_path, api_key="test-key", opener=opener)

    def test_http_failure_does_not_leak_provider_body_or_key(self):
        opener = Mock(side_effect=HTTPError(
            "https://generativelanguage.googleapis.com/private",
            403,
            "forbidden",
            {"x-goog-request-id": "req-sanitized-test"},
            io.BytesIO(json.dumps({
                "error": {
                    "status": "PERMISSION_DENIED",
                    "message": "Rejected key test-key-never-logged. Enable the API for this project.",
                }
            }).encode()),
        ))
        with self.assertLogs("smh.gemini_analysis", level="WARNING") as captured:
            with self.assertRaisesRegex(GeminiAnalysisError, "HTTP 403"):
                analyze_chart_with_gemini(
                    self.image_path,
                    api_key="test-key-never-logged",
                    opener=opener,
                )
        joined_logs = "\n".join(captured.output)
        self.assertIn("req-sanitized-test", joined_logs)
        self.assertIn("[REDACTED]", joined_logs)
        self.assertNotIn("test-key-never-logged", joined_logs)
        self.assertEqual(opener.call_count, 1)

    def test_model_not_found_is_reported_without_raw_provider_details(self):
        opener = Mock(side_effect=HTTPError(
            "https://generativelanguage.googleapis.com/private",
            404,
            "not found",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "status": "NOT_FOUND",
                    "message": "Models are not available for this secret value.",
                }
            }).encode()),
        ))
        with self.assertRaisesRegex(
                GeminiAnalysisError, "Gemini model 'gemini-test' was not found"):
            analyze_chart_with_gemini(
                self.image_path, api_key="test-key", opener=opener, model="gemini-test")

    def test_service_outage_is_reported_as_retryable(self):
        def unavailable():
            return HTTPError(
                "https://generativelanguage.googleapis.com/private",
                503,
                "unavailable",
                {},
                io.BytesIO(json.dumps({
                    "error": {
                        "status": "UNAVAILABLE",
                        "message": "Service temporarily unavailable.",
                    }
                }).encode()),
            )

        opener = Mock(side_effect=[unavailable(), unavailable()])
        sleeper = Mock()
        with self.assertRaisesRegex(
                GeminiAnalysisError, "temporarily unavailable \\(HTTP 503\\)"):
            analyze_chart_with_gemini(
                self.image_path,
                api_key="test-key",
                opener=opener,
                sleeper=sleeper,
                jitter=Mock(return_value=0.5),
                model="gemini-test",
            )
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(sleeper.call_count, 1)
        self.assertLessEqual(sum(call.args[0] for call in sleeper.call_args_list), 1.5)

    def test_primary_503_uses_verified_image_model_fallback_without_retry_wait(self):
        unavailable = HTTPError(
            "https://generativelanguage.googleapis.com/private",
            503,
            "unavailable",
            {},
            io.BytesIO(json.dumps({
                "error": {"status": "UNAVAILABLE", "message": "Service temporarily unavailable."}
            }).encode()),
        )
        opener = Mock(side_effect=[
            unavailable,
            FakeResponse({"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis}]},
            }]}),
        ])
        sleeper = Mock()
        with patch("smh.gemini_analysis.MODEL", "gemini-3.8-flash"), \
                patch("smh.gemini_analysis.FALLBACK_MODEL", "gemini-3.5-flash"):
            result = analyze_chart_with_gemini(
                self.image_path,
                api_key="test-key",
                opener=opener,
                sleeper=sleeper,
                jitter=Mock(return_value=0.5),
            )
        self.assertEqual(result, self.analysis)
        self.assertEqual(opener.call_count, 2)
        self.assertTrue(opener.call_args_list[0].args[0].full_url.endswith(
            "/models/gemini-3.8-flash:streamGenerateContent?alt=sse"))
        self.assertTrue(opener.call_args_list[1].args[0].full_url.endswith(
            "/models/gemini-3.5-flash:streamGenerateContent?alt=sse"))
        sleeper.assert_not_called()

    def test_503_honors_retry_after_then_returns_complete_analysis(self):
        first_error = HTTPError(
            "https://generativelanguage.googleapis.com/private",
            503,
            "unavailable",
            {"Retry-After": "1", "x-goog-request-id": "request-503"},
            io.BytesIO(json.dumps({
                "error": {
                    "status": "UNAVAILABLE",
                    "message": "Service temporarily unavailable.",
                }
            }).encode()),
        )
        opener = Mock(side_effect=[
            first_error,
            FakeResponse({"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis}]},
            }]}),
        ])
        sleeper = Mock()
        result = analyze_chart_with_gemini(
            self.image_path,
            api_key="test-key",
            opener=opener,
            sleeper=sleeper,
            jitter=Mock(return_value=0.5),
            model="gemini-test",
        )
        self.assertEqual(result, self.analysis)
        self.assertEqual(opener.call_count, 2)
        sleeper.assert_called_once_with(1.0)

    def test_transient_429_retries_but_hard_quota_does_not(self):
        transient_429 = HTTPError(
            "https://generativelanguage.googleapis.com/private",
            429,
            "rate limited",
            {"Retry-After": "0.1"},
            io.BytesIO(json.dumps({
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Too many requests; retry shortly.",
                }
            }).encode()),
        )
        opener = Mock(side_effect=[
            transient_429,
            FakeResponse({"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis}]},
            }]}),
        ])
        sleeper = Mock()
        self.assertEqual(
            analyze_chart_with_gemini(
                self.image_path,
                api_key="test-key",
                opener=opener,
                sleeper=sleeper,
                jitter=Mock(return_value=0.05),
            ),
            self.analysis,
        )
        self.assertEqual(opener.call_count, 2)
        sleeper.assert_called_once()

        hard_quota = HTTPError(
            "https://generativelanguage.googleapis.com/private",
            429,
            "quota exceeded",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Daily quota exceeded.",
                }
            }).encode()),
        )
        hard_quota_opener = Mock(side_effect=hard_quota)
        hard_quota_sleeper = Mock()
        with self.assertRaisesRegex(GeminiAnalysisError, "quota"):
            analyze_chart_with_gemini(
                self.image_path,
                api_key="test-key",
                opener=hard_quota_opener,
                sleeper=hard_quota_sleeper,
                jitter=Mock(return_value=0.05),
            )
        self.assertEqual(hard_quota_opener.call_count, 1)
        hard_quota_sleeper.assert_not_called()

    def test_503_retry_after_beyond_wait_budget_is_not_retried(self):
        opener = Mock(side_effect=HTTPError(
            "https://generativelanguage.googleapis.com/private",
            503,
            "unavailable",
            {"Retry-After": "60"},
            io.BytesIO(b"{}"),
        ))
        sleeper = Mock()
        with self.assertRaisesRegex(GeminiAnalysisError, "temporarily unavailable"):
            analyze_chart_with_gemini(
                self.image_path,
                api_key="test-key",
                opener=opener,
                sleeper=sleeper,
                jitter=Mock(return_value=0.5),
                model="gemini-test",
            )
        self.assertEqual(opener.call_count, 1)
        sleeper.assert_not_called()

    def test_retry_timeout_is_capped_by_total_request_deadline(self):
        first_error = HTTPError(
            "https://generativelanguage.googleapis.com/private",
            503,
            "unavailable",
            {"Retry-After": "0.05"},
            io.BytesIO(json.dumps({
                "error": {
                    "status": "UNAVAILABLE",
                    "message": "Service temporarily unavailable.",
                }
            }).encode()),
        )
        opener = Mock(side_effect=[
            first_error,
            FakeResponse({"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": self.analysis}]},
            }]}),
        ])
        clock = Mock(side_effect=[0.0, 0.0, 17.8, 17.8, 17.8])
        result = analyze_chart_with_gemini(
            self.image_path,
            api_key="test-key",
            opener=opener,
            sleeper=Mock(),
            jitter=Mock(return_value=0.05),
            monotonic=clock,
            model="gemini-test",
        )
        self.assertEqual(result, self.analysis)
        self.assertEqual(opener.call_count, 2)
        self.assertAlmostEqual(opener.call_args_list[1].kwargs["timeout"], 0.2)

    def test_invalid_key_error_gives_key_specific_next_step(self):
        opener = Mock(side_effect=HTTPError(
            "https://generativelanguage.googleapis.com/private",
            400,
            "bad request",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "API key not valid. Please pass a valid API key.",
                }
            }).encode()),
        ))
        with self.assertRaisesRegex(GeminiAnalysisError, "API key"):
            analyze_chart_with_gemini(self.image_path, api_key="test-key", opener=opener)


if __name__ == "__main__":
    unittest.main()
