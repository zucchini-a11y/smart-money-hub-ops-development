from __future__ import annotations

import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from io import BytesIO

from smart_money_hub_bot.bot import SmartMoneyHubBot
from smart_money_hub_bot.gemini_coach import GEMINI_MODEL
from smart_money_hub_bot.personal_reply_assistant import (
    PersonalReplyDraft,
    PersonalReplyGenerationError,
    PersonalTelegramReplyAssistant,
)
from smart_money_hub_bot.storage import Repository
from smart_money_hub_bot.telegram_api import TelegramAPIError

ADMIN_ID = 701
CONNECTION_ID = "synthetic-business-connection"
CHAT_ID = 808


def _provider_response(reply: str, needs_owner_input: bool = False) -> MagicMock:
    payload = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "reply": reply,
                                    "needs_owner_input": needs_owner_input,
                                }
                            )
                        }
                    ]
                },
            }
        ]
    }
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return response


class FakeBusinessAPI:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.business_messages: list[dict] = []
        self.send_error: TelegramAPIError | None = None

    def send_message(self, chat_id: int, text: str, *args, **kwargs) -> None:
        self.messages.append({"chat_id": chat_id, "text": text})

    def send_message_with_result(
        self, chat_id: int, text: str, *, business_connection_id: str
    ) -> dict:
        if self.send_error:
            raise self.send_error
        item = {
            "chat_id": chat_id,
            "text": text,
            "business_connection_id": business_connection_id,
        }
        self.business_messages.append(item)
        return {"message_id": len(self.business_messages) + 100}


class FakeAssistant:
    def __init__(self, draft: PersonalReplyDraft | None = None, error=None) -> None:
        self.draft = draft or PersonalReplyDraft("Thanks for reaching out.", False)
        self.error = error
        self.calls: list[dict] = []

    def generate(self, message: str, *, history=None) -> PersonalReplyDraft:
        self.calls.append({"message": message, "history": history or []})
        if self.error:
            raise self.error
        return self.draft


class PersonalReplyAssistantProviderTests(unittest.TestCase):
    def test_uses_only_the_pinned_model_and_passes_bounded_history(self) -> None:
        assistant = PersonalTelegramReplyAssistant("synthetic-key")
        history = []
        for index in range(8):
            history.extend(
                [
                    {"role": "user", "text": f"user {index}"},
                    {"role": "model", "text": f"assistant {index}"},
                ]
            )
        with patch(
            "smart_money_hub_bot.personal_reply_assistant.urlopen",
            return_value=_provider_response("Sounds good, thank you."),
        ) as mocked_urlopen:
            result = assistant.generate("Can we talk tomorrow?", history=history)

        self.assertEqual(result.reply, "Sounds good, thank you.")
        self.assertFalse(result.needs_owner_input)
        self.assertEqual(mocked_urlopen.call_count, 1)
        request = mocked_urlopen.call_args.args[0]
        self.assertIn(f"/{GEMINI_MODEL}:generateContent", request.full_url)
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 384)
        self.assertEqual(
            [item["parts"][0]["text"] for item in payload["contents"][:-1]],
            [
                item
                for index in range(2, 8)
                for item in (f"user {index}", f"assistant {index}")
            ],
        )
        instruction = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("Never invent the owner's whereabouts", instruction)
        self.assertIn("AI assistant", instruction)

    def test_provider_rate_limit_is_surfaced_without_model_failover(self) -> None:
        assistant = PersonalTelegramReplyAssistant("synthetic-key")
        error = HTTPError(
            "https://example.invalid",
            429,
            "rate limited",
            Message(),
            BytesIO(b'{"error":"private provider details"}'),
        )
        with patch(
            "smart_money_hub_bot.personal_reply_assistant.urlopen",
            side_effect=error,
        ) as mocked_urlopen:
            with self.assertRaises(PersonalReplyGenerationError) as caught:
                assistant.generate("Hello")
        self.assertEqual(caught.exception.category, "rate_limit")
        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertNotIn("private provider details", str(caught.exception))

    def test_malformed_model_reply_is_rejected(self) -> None:
        assistant = PersonalTelegramReplyAssistant("synthetic-key")
        payload = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"reply":"leak"}'}]},
                }
            ]
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch(
            "smart_money_hub_bot.personal_reply_assistant.urlopen",
            return_value=response,
        ):
            with self.assertRaises(PersonalReplyGenerationError) as caught:
                assistant.generate("Hello")
        self.assertEqual(caught.exception.category, "invalid_reply_format")
        self.assertNotIn("leak", str(caught.exception))

    def test_sensitive_request_is_marked_for_owner_input(self) -> None:
        assistant = PersonalTelegramReplyAssistant("synthetic-key")
        with patch(
            "smart_money_hub_bot.personal_reply_assistant.urlopen",
            return_value=_provider_response(
                "I want to make sure I understand before responding.", True
            ),
        ):
            result = assistant.generate("Should I accept this loan?")
        self.assertTrue(result.needs_owner_input)

    def test_unsafe_trading_claim_is_rejected(self) -> None:
        assistant = PersonalTelegramReplyAssistant("synthetic-key")
        with patch(
            "smart_money_hub_bot.personal_reply_assistant.urlopen",
            return_value=_provider_response("Buy now; profit is guaranteed."),
        ):
            with self.assertRaises(PersonalReplyGenerationError) as caught:
                assistant.generate("What do you think of the market?")
        self.assertEqual(caught.exception.category, "unsafe_financial_claim")


class PersonalBusinessReplyFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "business-replies.sqlite3"
        self.api = FakeBusinessAPI()
        self.assistant = FakeAssistant()
        self.bot = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=ADMIN_ID,
            personal_reply_assistant=self.assistant,
        )

    def _connect(self, *, can_reply: bool = True, owner_id: int = ADMIN_ID) -> None:
        self.bot.handle_update(
            {
                "business_connection": {
                    "id": CONNECTION_ID,
                    "user": {"id": owner_id},
                    "is_enabled": True,
                    "rights": {"can_reply": can_reply},
                }
            }
        )

    def _opt_in(self) -> None:
        self._connect()
        self.bot.handle_update(self._business_message(1, "Original message"))
        self.assertEqual(self.assistant.calls, [])
        self.assertIn("Google Gemini", self.api.business_messages[-1]["text"])
        self.assertIn("Reply YES to agree", self.api.business_messages[-1]["text"])
        self.bot.handle_update(self._business_message(2, "YES"))
        self.assertEqual(self.assistant.calls, [])
        self.assertIn("earlier messages were not saved", self.api.business_messages[-1]["text"])

    def _business_message(
        self,
        message_id: int,
        text: str,
        *,
        sender_id: int = 999,
        connection_id: str = CONNECTION_ID,
        update_id: int | None = None,
    ) -> dict:
        update = {
            "business_message": {
                "business_connection_id": connection_id,
                "message_id": message_id,
                "chat": {"id": CHAT_ID, "type": "private"},
                "from": {"id": sender_id},
                "text": text,
            }
        }
        if update_id is not None:
            update["update_id"] = update_id
        return update

    def test_enabled_admin_connection_replies_via_business_account(self) -> None:
        self._opt_in()
        self.bot.handle_update(self._business_message(3, "Hi there", update_id=501))

        self.assertEqual(len(self.api.business_messages), 3)
        sent = self.api.business_messages[-1]
        self.assertEqual(sent["chat_id"], CHAT_ID)
        self.assertEqual(sent["business_connection_id"], CONNECTION_ID)
        self.assertEqual(sent["text"], "Thanks for reaching out.")
        self.assertEqual(self.assistant.calls[0]["message"], "Hi there")
        turn = self.bot.store.recent_personal_business_reply_history(
            CONNECTION_ID, CHAT_ID
        )
        self.assertEqual(
            turn,
            [
                {"role": "user", "text": "Hi there"},
                {"role": "model", "text": "Thanks for reaching out."},
            ],
        )

    def test_follow_up_gets_recent_context_and_duplicate_update_is_not_replied_to(self) -> None:
        self._opt_in()
        update = self._business_message(3, "I prefer Friday.", update_id=502)
        self.bot.handle_update(update)
        self.bot.handle_update(update)
        self.bot.handle_update(self._business_message(4, "What time works?", update_id=503))

        self.assertEqual(len(self.api.business_messages), 4)
        self.assertEqual(len(self.assistant.calls), 2)
        self.assertEqual(
            self.assistant.calls[1]["history"],
            [
                {"role": "user", "text": "I prefer Friday."},
                {"role": "model", "text": "Thanks for reaching out."},
            ],
        )

    def test_only_six_completed_turns_are_retained_for_context(self) -> None:
        self._opt_in()
        for message_id in range(1, 9):
            self.bot.handle_update(
                self._business_message(message_id + 2, f"Message {message_id}")
            )

        history = self.bot.store.recent_personal_business_reply_history(
            CONNECTION_ID, CHAT_ID
        )
        self.assertEqual(len(history), 12)
        self.assertEqual(history[0], {"role": "user", "text": "Message 3"})
        self.assertEqual(history[-1]["role"], "model")
        connection = self.bot.store._connect()
        try:
            retained = connection.execute(
                """
                SELECT COUNT(*) FROM personal_business_reply_turns
                WHERE connection_id = ? AND chat_id = ? AND response_status = 'sent'
                """,
                (CONNECTION_ID, CHAT_ID),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(retained, 6)

    def test_wrong_owner_or_missing_reply_permission_cannot_reply(self) -> None:
        self._connect(owner_id=ADMIN_ID + 1)
        self.bot.handle_update(self._business_message(1, "Hello"))
        self.assertEqual(self.api.business_messages, [])

        self._connect(can_reply=False)
        self.bot.handle_update(self._business_message(2, "Hello again"))
        self.assertEqual(self.api.business_messages, [])
        self.assertEqual(self.assistant.calls, [])

    def test_owner_messages_are_not_answered(self) -> None:
        self._opt_in()
        self.bot.handle_update(
            self._business_message(3, "I sent this", sender_id=ADMIN_ID)
        )
        self.assertEqual(len(self.api.business_messages), 2)
        self.assertEqual(self.assistant.calls, [])

    def test_sensitive_reply_is_held_and_owner_notified(self) -> None:
        self._opt_in()
        self.assistant.draft = PersonalReplyDraft(
            "I want to check this first.", needs_owner_input=True
        )
        self.bot.handle_update(self._business_message(3, "Should I invest?"))

        self.assertEqual(len(self.api.business_messages), 2)
        self.assertEqual(len(self.api.messages), 1)
        self.assertIn("needs your input", self.api.messages[0]["text"])
        self.assertEqual(
            self.bot.store.get_personal_business_connection(CONNECTION_ID)["enabled"],
            1,
        )
        connection = self.bot.store._connect()
        try:
            status = connection.execute(
                """
                SELECT response_status FROM personal_business_reply_turns
                WHERE incoming_message_id = 3
                """
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(status, "needs_owner_input")
        connection = self.bot.store._connect()
        try:
            stored_message = connection.execute(
                """
                SELECT incoming_text FROM personal_business_reply_turns
                WHERE incoming_message_id = 3
                """
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(stored_message, "")

    def test_generation_failure_is_held_without_local_fallback(self) -> None:
        self._opt_in()
        self.assistant.error = PersonalReplyGenerationError("rate_limit")
        self.bot.handle_update(self._business_message(3, "A personal message"))
        self.assertEqual(len(self.api.business_messages), 2)
        self.assertEqual(self.api.messages[0]["chat_id"], ADMIN_ID)
        self.assertIn("rate_limit", self.api.messages[0]["text"])

    def test_send_failure_is_not_retried_automatically(self) -> None:
        self._opt_in()
        self.api.send_error = TelegramAPIError(
            "Forbidden", error_code=403, delivery_unknown=False
        )
        update = self._business_message(3, "Hello", update_id=505)
        self.bot.handle_update(update)
        self.bot.handle_update(update)
        self.assertEqual(len(self.assistant.calls), 1)
        self.assertEqual(len(self.api.business_messages), 2)
        self.assertIn("not be retried automatically", self.api.messages[-1]["text"])

    def test_disconnecting_business_connection_clears_saved_history(self) -> None:
        self._opt_in()
        self.bot.handle_update(self._business_message(3, "Hello"))
        self.bot.handle_update(
            {
                "business_connection": {
                    "id": CONNECTION_ID,
                    "user": {"id": ADMIN_ID},
                    "is_enabled": False,
                    "rights": {"can_reply": False},
                }
            }
        )
        self.assertEqual(
            self.bot.store.recent_personal_business_reply_history(
                CONNECTION_ID, CHAT_ID
            ),
            [],
        )
        self.bot.handle_update(self._business_message(4, "No longer authorized"))
        self.assertEqual(len(self.api.business_messages), 3)

    def test_deletion_update_removes_that_turn_from_future_context(self) -> None:
        self._opt_in()
        self.bot.handle_update(self._business_message(3, "Keep this context"))
        self.bot.handle_update(
            {
                "deleted_business_messages": {
                    "business_connection_id": CONNECTION_ID,
                    "chat": {"id": CHAT_ID},
                    "message_ids": [3],
                }
            }
        )
        self.assertEqual(
            self.bot.store.recent_personal_business_reply_history(
                CONNECTION_ID, CHAT_ID
            ),
            [],
        )

    def test_stop_erases_context_and_disables_future_ai_processing(self) -> None:
        self._opt_in()
        self.bot.handle_update(self._business_message(3, "A saved exchange"))
        self.bot.handle_update(self._business_message(4, "STOP"))
        self.assertEqual(
            self.bot.store.recent_personal_business_reply_history(
                CONNECTION_ID, CHAT_ID
            ),
            [],
        )
        self.assertEqual(
            self.bot.store.get_personal_business_reply_consent(
                CONNECTION_ID, CHAT_ID
            )["consent_state"],
            "declined",
        )
        self.bot.handle_update(self._business_message(5, "Do not process this"))
        self.assertEqual(len(self.assistant.calls), 1)
        self.assertIn("AI-assisted replies are now off", self.api.business_messages[-1]["text"])

    def test_delete_erases_context_without_revoking_consent(self) -> None:
        self._opt_in()
        self.bot.handle_update(self._business_message(3, "Saved context"))
        self.bot.handle_update(self._business_message(4, "DELETE"))
        self.assertEqual(
            self.bot.store.recent_personal_business_reply_history(
                CONNECTION_ID, CHAT_ID
            ),
            [],
        )
        self.assertEqual(
            self.bot.store.get_personal_business_reply_consent(
                CONNECTION_ID, CHAT_ID
            )["consent_state"],
            "consented",
        )

    def test_consent_is_required_before_any_message_reaches_gemini(self) -> None:
        self._connect()
        self.bot.handle_update(self._business_message(1, "Sensitive initial text"))
        self.assertEqual(self.assistant.calls, [])
        connection = self.bot.store._connect()
        try:
            stored_text = connection.execute(
                """
                SELECT incoming_text FROM personal_business_reply_turns
                WHERE connection_id = ? AND chat_id = ? AND incoming_message_id = 1
                """,
                (CONNECTION_ID, CHAT_ID),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(stored_text, "")
        self.bot.handle_update(self._business_message(2, "YES"))
        self.assertEqual(self.assistant.calls, [])
        self.bot.handle_update(self._business_message(3, "New consented message"))
        self.assertEqual(self.assistant.calls[0]["message"], "New consented message")

    def test_failed_consent_notice_is_retried_without_saving_message_text(self) -> None:
        self._connect()
        self.api.send_error = TelegramAPIError(
            "Forbidden", error_code=403, delivery_unknown=False
        )
        self.bot.handle_update(self._business_message(1, "Private first message"))
        self.assertEqual(self.assistant.calls, [])
        self.api.send_error = None
        self.bot.handle_update(self._business_message(2, "A later message"))

        self.assertEqual(self.assistant.calls, [])
        self.assertIn("Google Gemini", self.api.business_messages[-1]["text"])
        connection = self.bot.store._connect()
        try:
            stored_texts = connection.execute(
                """
                SELECT incoming_text FROM personal_business_reply_turns
                WHERE connection_id = ? AND chat_id = ?
                """,
                (CONNECTION_ID, CHAT_ID),
            ).fetchall()
        finally:
            connection.close()
        self.assertTrue(all(row[0] == "" for row in stored_texts))

    def test_restart_scrubs_interrupted_content_without_retrying(self) -> None:
        self._opt_in()
        self.bot.store.create_personal_business_reply_turn(
            connection_id=CONNECTION_ID,
            chat_id=CHAT_ID,
            incoming_message_id=99,
            incoming_text="Do not retain interrupted content",
        )
        restarted = SmartMoneyHubBot(
            self.api,
            str(self.database_path),
            admin_id=ADMIN_ID,
            personal_reply_assistant=self.assistant,
        )

        self.assertEqual(restarted._personal_reply_recovery_count, 1)
        connection = restarted.store._connect()
        try:
            row = connection.execute(
                """
                SELECT incoming_text, response_status
                FROM personal_business_reply_turns
                WHERE incoming_message_id = 99
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(tuple(row), ("", "failed"))
        self.assertEqual(self.assistant.calls, [])

    def test_regular_bot_message_does_not_enter_personal_assistant(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "message_id": 1,
                    "chat": {"id": 333, "type": "private"},
                    "from": {"id": 444},
                    "text": "menu",
                }
            }
        )
        self.assertEqual(self.assistant.calls, [])
        self.assertEqual(self.api.business_messages, [])
