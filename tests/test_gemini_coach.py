import json
import tempfile
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError

from smart_money_hub_bot.bot import SmartMoneyHubBot
from smart_money_hub_bot.coach import CoachProviderError, RuleBasedCoachService
from smart_money_hub_bot.gemini_coach import (
    GEMINI_ENDPOINT,
    GEMINI_MODEL,
    GeminiCoachService,
)
from smart_money_hub_bot.message_router import CoachMessageRouter
from smart_money_hub_bot.telegram_api import TelegramAPI


def _response(answer: str, needs_review: bool = False) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "answer": answer,
                                        "needs_review": needs_review,
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
    ).encode("utf-8")
    return response


def _provider_error(
    status_code: int,
    provider_status: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> HTTPError:
    response_headers = Message()
    for name, value in (headers or {}).items():
        response_headers[name] = value
    body = json.dumps(
        {
            "error": {
                "code": status_code,
                "status": provider_status,
                "message": message,
            }
        }
    ).encode("utf-8")
    return HTTPError(
        GEMINI_ENDPOINT,
        status_code,
        "provider error",
        response_headers,
        BytesIO(body),
    )


class _EmptyKnowledgeStore:
    def approved_knowledge_items(self):
        return []


class _UncertainService:
    def evaluate(self, message, *, history=None, profile=None):
        from smart_money_hub_bot.coach import CoachReply

        return CoachReply(
            "I am not certain about this yet.",
            "BOS",
            (),
            "",
            requires_review=True,
        )


class GeminiCoachTests(unittest.TestCase):
    def test_missing_key_falls_back_without_attempting_a_network_request(self) -> None:
        service = GeminiCoachService("")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        routed = router.route(321, "What is BOS?")
        reply = routed.reply
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", reply.response)
        self.assertEqual(routed.response_path, "fallback")

    def test_gemini_response_uses_fixed_free_model_and_key_header(self) -> None:
        service = GeminiCoachService("test-secret-value")
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_response("A BOS is a break through a relevant swing."),
        ) as mocked_urlopen:
            reply = service.evaluate("What is BOS?")

        request = mocked_urlopen.call_args.args[0]
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertEqual(GEMINI_MODEL, "gemini-3.8-flash")
        self.assertEqual(request.full_url, GEMINI_ENDPOINT)
        self.assertEqual(headers["x-goog-api-key"], "test-secret-value")
        self.assertNotIn("test-secret-value", request.full_url)
        self.assertIn("relevant swing", reply.response)
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertFalse(reply.requires_review)

    def test_conversation_context_is_bounded_and_isolated_per_member(self) -> None:
        service = GeminiCoachService("test-key")
        history_a = [
            {"question": "Alice-only coaching detail", "coach_response": "Alice reply"}
        ]
        history_b = [
            {"question": "Bob-only coaching detail", "coach_response": "Bob reply"}
        ]
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=[_response("Answer A"), _response("Answer B")],
        ) as mocked_urlopen:
            service.evaluate("What is BOS?", history=history_a)
            service.evaluate("What is CHoCH?", history=history_b)

        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in mocked_urlopen.call_args_list
        ]
        first = json.dumps(payloads[0])
        second = json.dumps(payloads[1])
        self.assertIn("Alice-only coaching detail", first)
        self.assertNotIn("Bob-only coaching detail", first)
        self.assertIn("Bob-only coaching detail", second)
        self.assertNotIn("Alice-only coaching detail", second)
        self.assertNotIn("telegram_id", first.casefold())
        self.assertNotIn("telegram_id", second.casefold())

    def test_quota_error_is_sanitized_and_router_falls_back_locally(self) -> None:
        service = GeminiCoachService("do-not-log-this-key")
        api_errors = [
            _provider_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded."),
            _provider_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded."),
        ]
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", side_effect=api_errors
        ) as mocked_urlopen, patch("smart_money_hub_bot.gemini_coach.time.sleep") as sleep:
            with self.assertRaises(CoachProviderError) as caught:
                service.evaluate("What is BOS?")
            router = CoachMessageRouter(service, _EmptyKnowledgeStore())
            reply = router.route(123, "What is BOS?").reply
        self.assertEqual(mocked_urlopen.call_count, 2)
        sleep.assert_not_called()
        self.assertEqual(caught.exception.failure_kind, "rate_limit")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.provider_status, "RESOURCE_EXHAUSTED")
        self.assertEqual(
            caught.exception.provider_message,
            "Google reports a rate limit or quota restriction.",
        )
        self.assertIsNotNone(caught.exception.elapsed_ms)
        self.assertNotIn("do-not-log-this-key", str(caught.exception))
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", reply.response)

    def test_service_unavailable_falls_back_locally(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        api_errors = [
            _provider_error(
                503,
                "UNAVAILABLE",
                "The model is overloaded. Prompt: What is BOS?",
                headers={
                    "Date": "Thu, 22 Oct 2026 08:00:00 GMT",
                    "Retry-After": "0",
                    "Content-Type": "application/json",
                    "X-Private-Diagnostic": "must-not-be-logged",
                },
            ),
            _provider_error(
                503,
                "UNAVAILABLE",
                "The model is overloaded. Prompt: What is BOS?",
                headers={"Retry-After": "3"},
            ),
        ]
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", side_effect=api_errors
        ) as mocked_urlopen, patch(
            "smart_money_hub_bot.gemini_coach.time.sleep"
        ) as sleep, self.assertLogs("smart_money_hub_bot", level="WARNING") as logs:
            routed = router.route(124, "What is BOS?")
        reply = routed.reply
        self.assertEqual(mocked_urlopen.call_count, 2)
        sleep.assert_called_once_with(0.0)
        self.assertIn("Break of Structure", reply.response)
        self.assertEqual(routed.response_path, "fallback")
        joined_logs = "\n".join(logs.output)
        self.assertIn("http_status=503", joined_logs)
        self.assertIn("google_status=UNAVAILABLE", joined_logs)
        self.assertIn(
            "Google reports the generation service is temporarily unavailable.",
            joined_logs,
        )
        self.assertIn("retry-after", joined_logs)
        self.assertNotIn("Prompt: What is BOS?", joined_logs)
        self.assertNotIn("must-not-be-logged", joined_logs)
        self.assertNotIn("test-key", joined_logs)

    def test_single_503_retry_succeeds_within_existing_deadline(self) -> None:
        service = GeminiCoachService("test-key", timeout_seconds=3)
        first_error = _provider_error(
            503, "UNAVAILABLE", "The model is overloaded."
        )
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=[first_error, _response("Recovered after one retry.")],
        ) as mocked_urlopen, patch(
            "smart_money_hub_bot.gemini_coach.time.sleep"
        ) as sleep:
            reply = service.evaluate("What is liquidity?")

        self.assertEqual(reply.response, "Recovered after one retry.")
        self.assertEqual(mocked_urlopen.call_count, 2)
        sleep.assert_called_once_with(0.25)
        first_timeout = mocked_urlopen.call_args_list[0].kwargs["timeout"]
        second_timeout = mocked_urlopen.call_args_list[1].kwargs["timeout"]
        self.assertLessEqual(first_timeout, 3)
        self.assertLessEqual(second_timeout, first_timeout)
        self.assertGreater(second_timeout, 0)

    def test_timeout_uses_the_local_fallback(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=TimeoutError("request timeout"),
        ), self.assertLogs("smart_money_hub_bot", level="WARNING") as logs:
            routed = router.route(456, "Explain break of structure")
        self.assertEqual(routed.reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", routed.reply.response)
        self.assertEqual(routed.response_path, "fallback")
        self.assertIn("kind=client_timeout", "\n".join(logs.output))

    def test_network_failure_is_not_retried(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=URLError("temporary DNS failure"),
        ) as mocked_urlopen, self.assertLogs(
            "smart_money_hub_bot", level="WARNING"
        ) as logs:
            routed = router.route(457, "What is liquidity?")

        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(routed.response_path, "fallback")
        self.assertIn("kind=network", "\n".join(logs.output))

    def test_ai_uncertainty_is_marked_for_admin_review(self) -> None:
        router = CoachMessageRouter(_UncertainService(), _EmptyKnowledgeStore())
        routed = router.route(789, "What is BOS?")
        self.assertIsNotNone(routed.assessment)
        self.assertEqual(routed.assessment.confidence, "low")
        self.assertTrue(routed.assessment.needs_research)
        self.assertIn("flagged", routed.reply.response)
        self.assertEqual(routed.response_path, "fallback")

    def test_simple_and_unvetted_messages_do_not_call_the_gemini_provider(self) -> None:
        provider = Mock()
        router = CoachMessageRouter(provider, _EmptyKnowledgeStore())
        self.assertEqual(router.route(987, "Hi").intent, "greeting")
        self.assertEqual(router.route(987, "Thanks").response_path, "local_response")
        unknown = router.route(987, "What is the latest inflation report today?")
        self.assertTrue(unknown.assessment.needs_research)
        provider.evaluate.assert_not_called()
        self.assertEqual(unknown.response_path, "local_response")

    def test_private_telegram_update_sends_gemini_answer_from_provider(self) -> None:
        synthetic_key = "test-key-never-log"
        synthetic_question = "What is liquidity?"
        generated_answer = "Gemini test answer: liquidity is resting orders around obvious highs and lows."
        api = TelegramAPI("synthetic-test-token")
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = SmartMoneyHubBot(
                api,
                str(Path(temp_dir) / "test.sqlite3"),
                coach_service=GeminiCoachService(synthetic_key),
            )
            update = {
                "update_id": 99,
                "message": {
                    "text": synthetic_question,
                    "chat": {"id": 654321, "type": "private"},
                    "from": {
                        "id": 123456,
                        "username": "synthetic_member",
                        "first_name": "Synthetic",
                    },
                },
            }
            with patch(
                "smart_money_hub_bot.gemini_coach.urlopen",
                return_value=_response(generated_answer),
            ) as mocked_urlopen:
                with patch.object(api, "_request") as mocked_telegram_request:
                    with self.assertLogs("smart_money_hub_bot", level="INFO") as logs:
                        bot.handle_update(update)

        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(mocked_telegram_request.call_count, 1)
        method, payload = mocked_telegram_request.call_args.args
        self.assertEqual(method, "sendMessage")
        self.assertEqual(payload["chat_id"], 654321)
        self.assertEqual(payload["text"], generated_answer)
        self.assertIn("Coach response path=gemini_success.", "\n".join(logs.output))
        self.assertIn(
            "Coach reply sent to Telegram (path=gemini_success).",
            "\n".join(logs.output),
        )
        self.assertNotIn(synthetic_question, "\n".join(logs.output))
        self.assertNotIn(synthetic_key, "\n".join(logs.output))
        self.assertNotIn("synthetic_member", "\n".join(logs.output))
        self.assertNotIn("654321", "\n".join(logs.output))

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload["contents"][-1]["parts"][0]["text"], synthetic_question
        )
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], synthetic_key)
        self.assertNotIn(synthetic_key, request.full_url)


if __name__ == "__main__":
    unittest.main()
