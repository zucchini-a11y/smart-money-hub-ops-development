import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError

from smart_money_hub_bot.coach import CoachProviderError, RuleBasedCoachService
from smart_money_hub_bot.gemini_coach import (
    GEMINI_ENDPOINT,
    GEMINI_MODEL,
    GeminiCoachService,
)
from smart_money_hub_bot.message_router import CoachMessageRouter


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
        reply = router.route(321, "What is BOS?").reply
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", reply.response)

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
        api_error = HTTPError(
            GEMINI_ENDPOINT,
            429,
            "quota exceeded",
            hdrs=None,
            fp=BytesIO(b"quota details"),
        )
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", side_effect=api_error
        ):
            with self.assertRaises(CoachProviderError) as caught:
                service.evaluate("What is BOS?")
            router = CoachMessageRouter(service, _EmptyKnowledgeStore())
            reply = router.route(123, "What is BOS?").reply
        self.assertEqual(caught.exception.failure_kind, "quota")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertNotIn("do-not-log-this-key", str(caught.exception))
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", reply.response)

    def test_service_unavailable_falls_back_locally(self) -> None:
        service = GeminiCoachService("test-key")
        api_error = HTTPError(
            GEMINI_ENDPOINT,
            503,
            "service unavailable",
            hdrs=None,
            fp=BytesIO(b"temporary service failure"),
        )
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", side_effect=api_error
        ):
            with self.assertRaises(CoachProviderError) as caught:
                service.evaluate("What is BOS?")
        self.assertEqual(caught.exception.failure_kind, "service_unavailable")
        self.assertEqual(caught.exception.status_code, 503)
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", side_effect=api_error
        ):
            reply = router.route(124, "What is BOS?").reply
        self.assertIn("Break of Structure", reply.response)

    def test_timeout_uses_the_local_fallback(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=TimeoutError("request timeout"),
        ):
            routed = router.route(456, "Explain break of structure")
        self.assertEqual(routed.reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", routed.reply.response)

    def test_ai_uncertainty_is_marked_for_admin_review(self) -> None:
        router = CoachMessageRouter(_UncertainService(), _EmptyKnowledgeStore())
        routed = router.route(789, "What is BOS?")
        self.assertIsNotNone(routed.assessment)
        self.assertEqual(routed.assessment.confidence, "low")
        self.assertTrue(routed.assessment.needs_research)
        self.assertIn("flagged", routed.reply.response)

    def test_simple_and_unvetted_messages_do_not_call_the_gemini_provider(self) -> None:
        provider = Mock()
        router = CoachMessageRouter(provider, _EmptyKnowledgeStore())
        self.assertEqual(router.route(987, "Hi").intent, "greeting")
        unknown = router.route(987, "What is the latest inflation report today?")
        self.assertTrue(unknown.assessment.needs_research)
        provider.evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
