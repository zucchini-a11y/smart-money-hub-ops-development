from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from unittest.mock import patch

from smart_money_hub_bot.telegram_api import TelegramAPI, TelegramAPIError


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return b'{"ok":true,"result":[]}'


class TelegramUpdateSubscriptionTests(unittest.TestCase):
    def test_download_file_retries_one_transient_network_failure(self) -> None:
        class ImageResponse:
            headers = {
                "Content-Length": "5",
                "Content-Type": "image/jpeg",
            }

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit: int) -> bytes:
                return b"image"

        api = TelegramAPI("synthetic-test-token")
        with (
            patch(
                "smart_money_hub_bot.telegram_api.urlopen",
                side_effect=[URLError("temporary connection failure"), ImageResponse()],
            ) as urlopen_mock,
            patch("smart_money_hub_bot.telegram_api.time.sleep"),
        ):
            image, mime_type = api.download_file("photos/example.jpg")

        self.assertEqual(image, b"image")
        self.assertEqual(mime_type, "image/jpeg")
        self.assertEqual(urlopen_mock.call_count, 2)

    def test_download_file_reports_network_failure_after_one_retry(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with (
            patch(
                "smart_money_hub_bot.telegram_api.urlopen",
                side_effect=[
                    URLError("temporary connection failure"),
                    URLError("temporary connection failure"),
                ],
            ) as urlopen_mock,
            patch("smart_money_hub_bot.telegram_api.time.sleep"),
        ):
            with self.assertRaises(TelegramAPIError) as caught:
                api.download_file("photos/example.jpg")

        self.assertEqual(caught.exception.failure_kind, "network")
        self.assertEqual(urlopen_mock.call_count, 2)

    def test_set_message_reaction_uses_one_standard_emoji(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(api, "_request", return_value=True) as request:
            result = api.set_message_reaction(-100123, 456, "👍")

        self.assertTrue(result)
        request.assert_called_once_with(
            "setMessageReaction",
            {
                "chat_id": -100123,
                "message_id": 456,
                "reaction": [{"type": "emoji", "emoji": "👍"}],
            },
        )

    def test_delete_message_uses_telegram_delete_method(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(api, "_request", return_value=True) as request:
            deleted = api.delete_message(123, 456)

        self.assertTrue(deleted)
        request.assert_called_once_with(
            "deleteMessage",
            {"chat_id": 123, "message_id": 456},
        )

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

    def test_business_reply_uses_the_authorized_business_connection(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(
            api, "_request", return_value={"message_id": 18}
        ) as request:
            result = api.send_message_with_result(
                456,
                "Thanks for reaching out.",
                business_connection_id="synthetic-business-connection",
            )

        self.assertEqual(result, {"message_id": 18})
        request.assert_called_once_with(
            "sendMessage",
            {
                "chat_id": 456,
                "text": "Thanks for reaching out.",
                "business_connection_id": "synthetic-business-connection",
            },
        )

    def test_send_photo_with_result_uses_file_id_and_html_caption(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        keyboard = {"inline_keyboard": [[{"text": "Open", "url": "https://t.me/example"}]]}
        with patch.object(
            api, "_request", return_value={"message_id": 19}
        ) as request:
            result = api.send_photo_with_result(
                -100123,
                "synthetic-file-id",
                caption="📊 <b>SMART MONEY HUB</b>",
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        self.assertEqual(result, {"message_id": 19})
        request.assert_called_once_with(
            "sendPhoto",
            {
                "chat_id": -100123,
                "photo": "synthetic-file-id",
                "caption": "📊 <b>SMART MONEY HUB</b>",
                "reply_markup": keyboard,
                "parse_mode": "HTML",
            },
        )

    def test_send_photo_with_result_uploads_a_local_image_as_multipart(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "session.png"
            image_path.write_bytes(b"\x89PNG\r\nsynthetic-image")
            with patch("smart_money_hub_bot.telegram_api.urlopen") as urlopen_mock:
                response = urlopen_mock.return_value.__enter__.return_value
                response.read.return_value = (
                    b'{"ok":true,"result":{"message_id":20}}'
                )
                result = api.send_photo_with_result(
                    -100123,
                    image_path,
                    caption="<b>New York</b>",
                    parse_mode="HTML",
                )

        self.assertEqual(result, {"message_id": 20})
        request = urlopen_mock.call_args.args[0]
        self.assertIn("sendPhoto", request.full_url)
        self.assertIn(b'name="chat_id"\r\n\r\n-100123', request.data)
        self.assertIn(b'name="caption"\r\n\r\n<b>New York</b>', request.data)
        self.assertIn(b'filename="session.png"', request.data)
        self.assertIn(b"image/png", request.data)
        self.assertIn(b"\x89PNG\r\nsynthetic-image", request.data)

    def test_edit_message_text_preserves_inline_button_and_html(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        keyboard = {"inline_keyboard": [[{"text": "Vote", "url": "https://t.me/c/1/2"}]]}
        with patch.object(api, "_request", return_value={"message_id": 17}) as request:
            result = api.edit_message_text(
                -100123,
                17,
                "📊 <b>Poll preview</b>",
                reply_markup=keyboard,
                parse_mode="HTML",
            )

        self.assertEqual(result, {"message_id": 17})
        request.assert_called_once_with(
            "editMessageText",
            {
                "chat_id": -100123,
                "message_id": 17,
                "text": "📊 <b>Poll preview</b>",
                "reply_markup": keyboard,
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

    def test_send_message_with_result_can_target_a_forum_topic(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(api, "_request", return_value={"message_id": 89}) as request:
            result = api.send_message_with_result(
                -100123,
                "Approved topic post.",
                parse_mode="HTML",
                message_thread_id=456,
            )

        self.assertEqual(result, {"message_id": 89})
        request.assert_called_once_with(
            "sendMessage",
            {
                "chat_id": -100123,
                "text": "Approved topic post.",
                "parse_mode": "HTML",
                "message_thread_id": 456,
            },
        )

    def test_send_photo_with_result_can_target_a_forum_topic(self) -> None:
        api = TelegramAPI("synthetic-test-token")
        with patch.object(
            api, "_request", return_value={"message_id": 90}
        ) as request:
            result = api.send_photo_with_result(
                -100123,
                "synthetic-photo-id",
                caption="Approved image post.",
                parse_mode="HTML",
                message_thread_id=456,
            )

        self.assertEqual(result, {"message_id": 90})
        request.assert_called_once_with(
            "sendPhoto",
            {
                "chat_id": -100123,
                "photo": "synthetic-photo-id",
                "caption": "Approved image post.",
                "parse_mode": "HTML",
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
        self.assertNotIn("business_connection", payload["allowed_updates"])
        self.assertNotIn("business_message", payload["allowed_updates"])
        self.assertNotIn("edited_business_message", payload["allowed_updates"])
        self.assertNotIn("deleted_business_messages", payload["allowed_updates"])
        self.assertNotIn("poll_answer", payload["allowed_updates"])


if __name__ == "__main__":
    unittest.main()
