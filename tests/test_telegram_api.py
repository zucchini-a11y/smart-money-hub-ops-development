from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from smart_money_hub_bot.telegram_api import TelegramAPI


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return b'{"ok":true,"result":[]}'


class TelegramUpdateSubscriptionTests(unittest.TestCase):
    def test_send_message_with_result_can_use_telegram_html_parse_mode(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(
            api,
            "_request",
            return_value={"message_id": 17},
        ) as request:
            result = api.send_message_with_result(
                123,
                "<b>Smart Money Hub</b>",
                parse_mode="HTML",
            )

        self.assertEqual(result, {"message_id": 17})
        request.assert_called_once_with(
            "sendMessage",
            {
                "chat_id": 123,
                "text": "<b>Smart Money Hub</b>",
                "parse_mode": "HTML",
            },
        )

    def test_send_message_can_target_a_forum_topic(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(api, "_request") as request:
            api.send_message(
                -100123,
                "A topic reply.",
                message_thread_id=456,
            )

        request.assert_called_once_with(
            "sendMessage",
            {
                "chat_id": -100123,
                "text": "A topic reply.",
                "message_thread_id": 456,
            },
        )

    def test_send_poll_uses_anonymous_quiz_and_topic(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(
            api,
            "_request",
            return_value={"message_id": 88},
        ) as request:
            result = api.send_poll(
                -100123,
                "Hypothetical SMC question?",
                ["Correct", "Incorrect"],
                0,
                "Wait for confirmation.",
                message_thread_id=456,
            )

        self.assertEqual(result, {"message_id": 88})
        request.assert_called_once_with(
            "sendPoll",
            {
                "chat_id": -100123,
                "question": "Hypothetical SMC question?",
                "options": ["Correct", "Incorrect"],
                "type": "quiz",
                "is_anonymous": True,
                "correct_option_id": 0,
                "explanation": "Wait for confirmation.",
                "message_thread_id": 456,
            },
        )

    def test_send_chat_action_can_target_a_forum_topic(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(api, "_request") as request:
            api.send_chat_action(
                -100123,
                "typing",
                message_thread_id=456,
            )

        request.assert_called_once_with(
            "sendChatAction",
            {
                "chat_id": -100123,
                "action": "typing",
                "message_thread_id": 456,
            },
            timeout=3,
        )

    def test_poll_subscription_includes_channel_posts_and_edits(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response()

        api = TelegramAPI("synthetic-test-token")
        with patch("smart_money_hub_bot.telegram_api.urlopen", side_effect=fake_urlopen):
            self.assertEqual(api.get_updates(offset=None), [])

        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertIn("channel_post", payload["allowed_updates"])
        self.assertIn("edited_channel_post", payload["allowed_updates"])
        self.assertIn("message", payload["allowed_updates"])
        self.assertIn("edited_message", payload["allowed_updates"])
        self.assertIn("poll", payload["allowed_updates"])
        self.assertIn("callback_query", payload["allowed_updates"])
        self.assertNotIn("poll_answer", payload["allowed_updates"])


if __name__ == "__main__":
    unittest.main()
