import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace as NS

from smh.support_api import (
    SupportApiClient,
    SupportApiError,
    process_shared_support_reply_once,
)


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


class SharedSupportClientTests(unittest.TestCase):
    def test_environment_gate_is_isolated_schema_only(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(SupportApiClient.from_environment(
                isolated_test=True, database_schema="smh_test"))

        enabled = {
            "SMH_SUPPORT_API_ENABLED": "true",
            "SMH_SUPPORT_API_URL": "https://support.example.test",
            "SMH_SUPPORT_SIGNALS_TOKEN": "t" * 40,
        }
        with patch.dict(os.environ, enabled, clear=True):
            with self.assertRaisesRegex(ValueError, "only for the isolated"):
                SupportApiClient.from_environment(
                    isolated_test=False, database_schema="smh_test")
            with self.assertRaisesRegex(ValueError, "only for the isolated"):
                SupportApiClient.from_environment(
                    isolated_test=True, database_schema="smh")

    def test_enabled_environment_requires_url_and_bot_token(self):
        with patch.dict(os.environ, {"SMH_SUPPORT_API_ENABLED": "true"}, clear=True):
            with self.assertRaisesRegex(ValueError, "URL and Signal bot token"):
                SupportApiClient.from_environment(
                    isolated_test=True, database_schema="smh_test")

    def test_create_case_uses_idempotent_request_and_bot_authentication(self):
        client = SupportApiClient("https://support.example.test", "t" * 40)
        opener = Mock()
        opener.open.return_value = Response(b'{"caseId":"case-12345678"}')
        client._opener = opener

        result = client.create_case(42, "Please check my access.", 12345)

        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/support/bot/cases"))
        self.assertEqual(request.get_header("Authorization"), f"Bearer {'t' * 40}")
        self.assertEqual(json.loads(request.data), {
            "requestId": "telegram-update-12345",
            "telegramUserId": 42,
            "question": "Please check my access.",
        })
        self.assertEqual(result["caseId"], "case-12345678")

    def test_api_error_does_not_expose_server_response_body(self):
        client = SupportApiClient("https://support.example.test", "t" * 40)
        opener = Mock()
        opener.open.side_effect = SupportApiError("network")
        client._opener = opener
        with self.assertRaises(SupportApiError) as caught:
            client.create_case(42, "A question.", 12345)
        self.assertEqual(str(caught.exception), "network")
        self.assertNotIn("question", str(caught.exception))


class SharedSupportReplyWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = Mock()
        self.api.claim_replies.return_value = {
            "replies": [{
                "replyId": "reply-12345678",
                "telegramUserId": "42",
                "text": "A staff member has reviewed your request.",
                "responderName": "Support",
            }]
        }
        self.api.acknowledge_reply = Mock(return_value={"status": "sent"})
        self.bot = NS(send_message=AsyncMock(return_value=NS(message_id=7)))

    async def test_successful_delivery_is_acknowledged_sent(self):
        processed = await process_shared_support_reply_once(self.api, self.bot)
        self.assertTrue(processed)
        self.bot.send_message.assert_awaited_once()
        self.assertIn("A staff member has reviewed", self.bot.send_message.await_args.kwargs["text"])
        self.api.acknowledge_reply.assert_called_once_with("reply-12345678", "sent")

    async def test_telegram_rejection_is_acknowledged_failed(self):
        class PermanentDeliveryError(Exception):
            pass

        self.bot.send_message.side_effect = PermanentDeliveryError("member blocked bot")
        await process_shared_support_reply_once(
            self.api, self.bot, permanent_errors=(PermanentDeliveryError,))
        self.api.acknowledge_reply.assert_called_once_with("reply-12345678", "failed")

    async def test_uncertain_telegram_delivery_is_not_retried(self):
        self.bot.send_message.side_effect = TimeoutError("simulated timeout")
        await process_shared_support_reply_once(self.api, self.bot)
        self.api.acknowledge_reply.assert_called_once_with("reply-12345678", "uncertain")

    async def test_invalid_reply_is_rejected_without_telegram_send(self):
        self.api.claim_replies.return_value = {
            "replies": [{
                "replyId": "reply-12345678",
                "telegramUserId": "not-a-user",
                "text": "A reply.",
                "responderName": "Support",
            }]
        }
        await process_shared_support_reply_once(self.api, self.bot)
        self.bot.send_message.assert_not_awaited()
        self.api.acknowledge_reply.assert_called_once_with("reply-12345678", "failed")

