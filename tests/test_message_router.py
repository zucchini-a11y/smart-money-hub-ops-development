import unittest

from smart_money_hub_bot.coach import RuleBasedCoachService
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
        self.assertIn("I won’t guess", result.reply.response)


if __name__ == "__main__":
    unittest.main()
