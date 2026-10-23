import unittest
from unittest.mock import Mock, patch

from smart_money_hub_bot.coach import (
    CoachProviderError,
    CoachReply,
    RuleBasedCoachService,
)
from smart_money_hub_bot.message_router import CoachMessageRouter


class _EmptyKnowledgeStore:
    def approved_knowledge_items(self):
        return []


class MessageRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = CoachMessageRouter(RuleBasedCoachService(), _EmptyKnowledgeStore())

    def test_simple_conversation_intents_are_immediate_and_varied(self) -> None:
        first_greeting = self.router.route(101, "Hi").reply.response
        next_greeting = self.router.route(101, "hello").reply.response
        self.assertNotEqual(first_greeting, next_greeting)
        self.assertIsNone(self.router.route(101, "Hey bro").assessment)

        self.assertIn(
            "morning",
            self.router.route(101, "Good morning").reply.response.casefold(),
        )
        thanks = self.router.route(101, "Thanks").reply.response.casefold()
        self.assertTrue(any(term in thanks for term in ("welcome", "anytime", "you got it")))
        farewell = self.router.route(101, "See you").reply.response.casefold()
        self.assertTrue(any(term in farewell for term in ("bye", "see you", "talk soon")))
        acknowledgement = self.router.route(101, "Okay")
        self.assertEqual(acknowledgement.intent, "acknowledgement")
        self.assertIsNone(acknowledgement.assessment)
        self.assertEqual(self.router.route(101, "Alright").intent, "acknowledgement")
        self.assertEqual(self.router.route(101, "What’s up?").intent, "greeting")

    def test_admin_greetings_use_a_more_formal_tone(self) -> None:
        response = self.router.route(
            101, "Good morning", profile={"is_admin": True}
        ).reply.response

        self.assertIn("Good morning.", response)
        self.assertTrue(
            any(phrase in response for phrase in ("assist you today", "help you with"))
        )

    def test_admin_context_reaches_provider_without_history(self) -> None:
        provider = Mock()
        provider.diagnostic_response_path = "gemini_success"
        provider.evaluate.return_value = CoachReply(
            "A respectful educational answer.", "Liquidity / SSL / BSL", (), ""
        )
        router = CoachMessageRouter(provider, _EmptyKnowledgeStore())

        router.route(102, "Explain liquidity", profile={"is_admin": True})

        self.assertIs(provider.evaluate.call_args.kwargs["profile"]["is_admin"], True)

    def test_admin_local_fallback_keeps_a_professional_tone(self) -> None:
        provider = Mock()
        provider.evaluate.side_effect = CoachProviderError("client_timeout")
        router = CoachMessageRouter(provider, _EmptyKnowledgeStore())

        routed = router.route(103, "What is liquidity?", profile={"is_admin": True})

        self.assertEqual(routed.response_path, "fallback")
        self.assertTrue(routed.reply.response.startswith("Certainly — "))

    def test_alias_phrasings_route_to_the_same_trading_topic(self) -> None:
        phrasings = (
            "What is BOS?",
            "Explain break of structure",
            "What does BOS mean?",
        )
        replies = [self.router.route(202, text) for text in phrasings]
        self.assertTrue(all(reply.reply.detected_topic == "BOS" for reply in replies))
        self.assertTrue(
            all("Break of Structure" in reply.reply.response for reply in replies)
        )
        self.assertTrue(all(reply.assessment and reply.assessment.confidence == "high" for reply in replies))

    def test_other_requested_trading_terms_have_local_keyword_guides(self) -> None:
        cases = (
            ("What is R:R?", "Risk:Reward"),
            ("Where should my stop loss go?", "Stop Loss"),
            ("How should I plan take profit?", "Take Profit"),
            ("What does FOMO mean?", "FOMO"),
            ("How do I avoid revenge trading?", "Revenge Trading"),
        )
        for message, topic in cases:
            with self.subTest(message=message):
                result = self.router.route(303, message)
                self.assertEqual(result.reply.detected_topic, topic)
                self.assertNotIn("I don’t have a vetted answer", result.reply.response)

    def test_unknown_current_question_is_not_guessed_and_is_flagged(self) -> None:
        result = self.router.route(404, "What is the latest inflation report today?")
        self.assertEqual(result.intent, "question")
        self.assertIsNotNone(result.assessment)
        self.assertEqual(result.assessment.topic, "Economic News and Fundamentals")
        self.assertIn("latest release", result.reply.response)
        self.assertIn("Share the headline or figures", result.reply.response)
        self.assertIn("administrator", result.reply.response)
        self.assertEqual(result.response_path, "fallback")

    def test_approved_knowledge_answers_before_gemini(self) -> None:
        provider = Mock()
        router = CoachMessageRouter(provider, _EmptyKnowledgeStore())
        approved_item = {
            "approved_answer": "Administrator-approved liquidity explanation."
        }
        with patch(
            "smart_money_hub_bot.message_router.find_approved_answer",
            return_value=approved_item,
        ):
            routed = router.route(505, "What is liquidity?")

        self.assertEqual(routed.response_path, "approved_knowledge")
        self.assertEqual(routed.reply.response, approved_item["approved_answer"])
        provider.evaluate.assert_not_called()

    def test_configured_provider_answer_is_labeled_for_diagnostics(self) -> None:
        class _GeminiProvider:
            diagnostic_response_path = "gemini_success"

            def evaluate(
                self, message, *, history=None, profile=None, request_id=None
            ):
                return CoachReply(
                    "Generated provider answer.",
                    "Liquidity / SSL / BSL",
                    (),
                    "",
                )

        router = CoachMessageRouter(_GeminiProvider(), _EmptyKnowledgeStore())
        routed = router.route(606, "What is liquidity?")
        self.assertEqual(routed.response_path, "gemini_success")
        self.assertEqual(routed.reply.response, "Generated provider answer.")


if __name__ == "__main__":
    unittest.main()
