import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from smart_money_hub_bot.bot import SmartMoneyHubBot


class _SupportClient:
    def __init__(self) -> None:
        self.created = []
        self.acknowledgements = []

    def create_case(self, telegram_user_id, question, update_id):
        self.created.append((telegram_user_id, question, update_id))
        return {"caseId": "case-12345678"}

    def claim_replies(self):
        return {
            "replies": [
                {
                    "replyId": "reply-12345678",
                    "caseId": "case-12345678",
                    "telegramUserId": "12345",
                    "text": "We can help with that.",
                    "responderName": "Support",
                }
            ]
        }

    def acknowledge_reply(self, reply_id, outcome):
        self.acknowledgements.append((reply_id, outcome))
        return {"status": outcome}


class SupportBotTests(unittest.TestCase):
    def test_contact_support_flow_runs_through_update_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            api = Mock()
            bot = SmartMoneyHubBot(
                api,
                str(Path(temp_dir) / "coach.sqlite3"),
                education_group_id=None,
            )
            support = _SupportClient()
            bot.support_api = support

            bot.handle_update(
                {
                    "update_id": 700,
                    "message": {
                        "message_id": 1,
                        "date": 1_800_000_000,
                        "text": "/support",
                        "from": {"id": 12345, "first_name": "Test"},
                        "chat": {"id": 12345, "type": "private"},
                    },
                }
            )
            bot.handle_update(
                {
                    "update_id": 701,
                    "message": {
                        "message_id": 2,
                        "date": 1_800_000_001,
                        "text": "I need help with my course access.",
                        "from": {"id": 12345, "first_name": "Test"},
                        "chat": {"id": 12345, "type": "private"},
                    },
                }
            )

            self.assertEqual(
                support.created,
                [(12345, "I need help with my course access.", 701)],
            )
            sent_text = [call.args[1] for call in api.send_message.call_args_list]
            self.assertTrue(any("Send one message" in text for text in sent_text))
            self.assertTrue(any("case-12345678" in text for text in sent_text))
            self.assertNotIn(12345, bot.sessions)

    def test_portal_reply_is_sent_and_acknowledged_by_the_originating_bot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            api = Mock()
            bot = SmartMoneyHubBot(
                api,
                str(Path(temp_dir) / "coach.sqlite3"),
                education_group_id=None,
            )
            support = _SupportClient()
            bot.support_api = support

            bot._deliver_support_replies()

            api.send_message.assert_called_once_with(12345, "We can help with that.")
            self.assertEqual(support.acknowledgements, [("reply-12345678", "sent")])

    def test_ambiguous_telegram_delivery_is_marked_uncertain_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            api = Mock()
            api.send_message.side_effect = TimeoutError("network timeout")
            bot = SmartMoneyHubBot(
                api,
                str(Path(temp_dir) / "coach.sqlite3"),
                education_group_id=None,
            )
            support = _SupportClient()
            bot.support_api = support

            bot._deliver_support_replies()

            self.assertEqual(support.acknowledgements, [("reply-12345678", "uncertain")])


if __name__ == "__main__":
    unittest.main()
