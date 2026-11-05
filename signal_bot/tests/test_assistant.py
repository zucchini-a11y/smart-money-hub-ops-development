import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from smh.assistant import DEFAULT_INACTIVE_REASON, detect_intent
from smh.config import Config
from smh.database import Database, now
from smh.handlers import Handlers
from smh.health import Health
from smh.publishing import Publisher
from smh.support_api import SupportApiError


class AssistantFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name)
        self.config = Config("123456789:TEST_TOKEN_NOT_REAL", 42, -1001, -1002, Path(self.temp.name))
        self.bot = NS(
            send_message=AsyncMock(return_value=NS(message_id=90)),
            send_photo=AsyncMock(return_value=NS(message_id=91)),
            get_me=AsyncMock(return_value=NS(id=1)),
        )
        self.publisher = Publisher(self.db, self.config, self.bot)

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    def ui(self):
        return Handlers(self.db, self.config, self.bot, self.publisher,
                        Health(self.db, self.config, self.bot))

    def update(self, user=77, text=""):
        return NS(
            effective_user=NS(id=user),
            effective_chat=NS(id=user, type="private"),
            message=NS(text=text, forward_origin=None),
            callback_query=NS(answer=AsyncMock(), data=None),
        )

    def last_message(self):
        return self.bot.send_message.await_args_list[-1]

    async def test_admin_without_active_draft_gets_clear_start_guidance(self):
        ui = self.ui()
        await ui.text(self.update(42, "hello"), None)

        message = self.last_message().args[1]
        self.assertIn("administrator menu", message.lower())
        self.assertIn("available options", message)
        self.assertNotIn("/start", message)

    async def test_unexpected_attachment_guides_member_without_slash_commands(self):
        ui = self.ui()
        await ui.assistant_unexpected_media(self.update(77))

        message = self.last_message().args[1]
        self.assertNotIn("/", message)
        self.assertIn("contact the administrator from the menu", message)

    async def test_first_time_and_returning_greetings_resume_saved_application(self):
        ui = self.ui()
        user = self.update(77, "/start")
        await ui.command(user, None)
        welcome = self.last_message().args[1]
        self.assertIn("Welcome", welcome)
        self.assertIn("WELCOME TO VAYDA SMART MONEY HUB", welcome)
        self.assertIn("type your question", welcome.lower())
        labels = [button.text for row in self.last_message().kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertEqual(len(labels), 3)
        self.assertEqual(labels[0], "🔐 Member Access")

        self.db.save_draft(77, {
            "kind": "destination_application", "destination": "education",
            "step": "answers", "answers": ["Beginner"], "revision": 2,
        })
        user.message.text = "/start"
        await ui.command(user, None)
        text = self.last_message().args[1]
        self.assertIn("WELCOME TO VAYDA SMART MONEY HUB", text)
        labels = [button.text for row in self.last_message().kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertIn("▶️ Continue my saved step", labels)
        self.assertIsNotNone(self.db.draft(77))

    async def test_legacy_approved_application_is_not_shown_as_current_destination_access(self):
        ui = self.ui()
        self.db.execute("INSERT INTO applications VALUES (77,'[]','approved','now')")
        user = self.update(77, "/start")

        await ui.command(user, None)
        start_text = self.last_message().args[1]
        self.assertIn("previous general application on file", start_text)
        self.assertIn("does not automatically grant access to a specific destination", start_text)
        self.assertNotIn("Previous application: approved", start_text)

        await ui.member_action(user, "member_status", {})
        status_text = self.last_message().args[1]
        self.assertIn("does not approve a specific destination", status_text)
        self.assertIn("shown separately for each destination", status_text)
        self.assertNotIn("Previous application: approved", status_text)

        user.message.text = "hello"
        await ui.text(user, None)
        self.assertIn("What would you like help with?", self.last_message().args[1])
        self.assertTrue(all(call.args[0] not in (-1001, -1002)
                            for call in self.bot.send_message.await_args_list))

    async def test_rule_based_questions_offer_configured_pro_link_without_channel_posts(self):
        self.config = replace(
            self.config, exness_partner_link="https://one.exnessonelink.com/a/safe-test"
        )
        ui = self.ui()
        user = self.update(77, "How can I join PRO Signals?")
        await ui.text(user, None)
        text = self.last_message().args[1]
        self.assertIn("🔐 <b>PRO SIGNALS ACCESS</b> 🎯", text)
        self.assertIn("📝 <b>HOW TO APPLY</b>", text)
        self.assertIn("Privately provide evidence of your initial funding", text)
        self.assertIn("An administrator will review your submission and make the final decision", text)
        self.assertIn("Your profits belong to you", text)
        self.assertIn("There is no fixed balance threshold applied by the bot.", text)
        self.assertIn("Submitting a screenshot does not automatically remove or approve anyone.", text)
        self.assertIn("Never deposit money solely to qualify for PRO Signals.", text)
        self.assertNotIn("PRO profit and funding reminder", text)
        self.assertIn("💰 <b>PRO PROFITS &amp; FUNDING — IMPORTANT</b>", text)
        self.assertEqual(self.last_message().kwargs["parse_mode"], "HTML")
        markup = self.last_message().kwargs["reply_markup"]
        buttons = [button for row in markup.inline_keyboard for button in row]
        self.assertEqual(len(buttons), 1)
        self.assertNotIn(self.config.exness_partner_link, text)
        self.assertIsNone(buttons[0].url)
        self.assertEqual(buttons[0].text, "Apply for PRO Signals")
        self.assertTrue(all(call.args[0] not in (-1001, -1002)
                            for call in self.bot.send_message.await_args_list))
        self.assertEqual(detect_intent("How do I join the Educational Group?"), "education")
        self.assertEqual(detect_intent("I need market analysis"), "analysis")
        self.assertEqual(detect_intent("how do I check my application status"), "status")

    async def test_unknown_question_does_not_store_or_forward_until_user_requests_admin(self):
        ui = self.ui()
        user = self.update(77, "What is the meaning of this unusual phrase?")
        await ui.text(user, None)
        self.assertEqual(self.db.rows("SELECT * FROM assistant_escalations"), [])
        markup = self.last_message().kwargs["reply_markup"]
        button = next(button for row in markup.inline_keyboard for button in row
                      if "Ask the Administrator" in button.text)

        user.callback_query.data = button.callback_data
        await ui.callback(user, None)
        self.assertTrue(self.db.get("assistant:contact_pending:77"))
        user.message.text = "Please help me understand how my access review works."
        await ui.text(user, None)

        cases = self.db.rows("SELECT * FROM assistant_escalations")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["user_id"], 77)
        self.assertEqual(cases[0]["status"], "open")
        self.assertIn("access review", cases[0]["question"])
        self.assertFalse(self.db.get("assistant:contact_pending:77"))
        acknowledgement = next(
            call.args[1] for call in reversed(self.bot.send_message.await_args_list)
            if call.args[0] == 77
        )
        self.assertIn("received by our support team", acknowledgement)
        self.assertIn("administrator or support team member", acknowledgement)
        self.assertNotIn(cases[0]["id"], acknowledgement)
        self.db.put("assistant:contact_pending:77", True)
        user.message.text = "A second unrelated question."
        await ui.text(user, None)
        self.assertEqual(self.db.rows("SELECT * FROM assistant_escalations"), cases)
        duplicate_acknowledgement = next(
            call.args[1] for call in reversed(self.bot.send_message.await_args_list)
            if call.args[0] == 77
        )
        self.assertIn("already in our support queue", duplicate_acknowledgement)
        self.assertNotIn(cases[0]["id"], duplicate_acknowledgement)
        destinations = [call.args[0] for call in self.bot.send_message.await_args_list]
        self.assertNotIn(42, destinations)
        self.assertNotIn(-1001, destinations)
        self.assertNotIn(-1002, destinations)
        self.assertEqual(set(destinations), {77})

    async def test_shared_support_case_uses_portal_and_skips_the_local_queue(self):
        ui = self.ui()
        support_api = NS(create_case=Mock(return_value={"caseId": "case-12345678"}))
        ui.support_api = support_api
        user = self.update(77, "Please check my membership status.")
        user.update_id = 314

        await ui.assistant_submit_contact(user, user.message.text)

        support_api.create_case.assert_called_once_with(
            77, "Please check my membership status.", 314)
        self.assertEqual(self.db.rows("SELECT * FROM assistant_escalations"), [])
        self.assertIn("shared support team", self.last_message().args[1])

    async def test_failed_shared_support_case_is_not_saved_to_the_local_queue(self):
        ui = self.ui()
        ui.support_api = NS(create_case=Mock(side_effect=SupportApiError("network")))

        await ui.assistant_submit_contact(
            self.update(77, "Please check my membership status."),
            "Please check my membership status.",
        )

        self.assertEqual(self.db.rows("SELECT * FROM assistant_escalations"), [])
        self.assertIn("was not submitted", self.last_message().args[1])

    async def test_admin_support_views_redirect_to_portal_without_showing_member_text(self):
        ui = self.ui()
        question = "Private member question that must stay in the portal."
        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('portal-only-case',77,?,'open','now','now')",
            (question,),
        )
        admin = self.update(42)

        await ui.assistant_admin_panel(admin)
        panel_text = self.last_message().args[1]
        panel_buttons = [button.text for row in self.last_message().kwargs["reply_markup"].inline_keyboard
                         for button in row]
        self.assertIn("Support Portal only", panel_text)
        self.assertNotIn(question, panel_text)
        self.assertNotIn("📥 Review support requests", panel_buttons)

        await ui.assistant_queue(admin)
        self.assertIn("Support Portal", self.last_message().args[1])
        self.assertNotIn(question, self.last_message().args[1])
        await ui.assistant_case(admin, "portal-only-case")
        self.assertIn("Support Portal", self.last_message().args[1])
        self.assertNotIn(question, self.last_message().args[1])

    async def test_sensitive_contact_text_is_not_saved_or_forwarded(self):
        ui = self.ui()
        user = self.update(77, "/contact")
        await ui.command(user, None)
        user.message.text = "My password is example-secret"
        await ui.text(user, None)
        self.assertEqual(self.db.rows("SELECT * FROM assistant_escalations"), [])
        self.assertNotIn("example-secret", str(self.bot.send_message.await_args_list))

    async def test_unrecognized_command_gets_help_instead_of_being_ignored(self):
        ui = self.ui()
        await ui.unknown_command(self.update(77, "/unknown"), None)
        self.assertIn("Choose a button", self.last_message().args[1])
        self.assertNotIn("/", self.last_message().args[1])
        labels = [button.text for row in self.last_message().kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertIn("📝 Apply for Access", labels)

    async def test_status_is_private_and_faq_can_be_updated_by_admin_only(self):
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,username,destination,answers,status,registration_status,funding_status,created,updated) "
            "VALUES ('req-77',77,'member','education','[]','pending_review','not_required','not_required','now','now')"
        )
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,username,destination,answers,status,registration_status,funding_status,created,updated) "
            "VALUES ('req-88',88,'other','pro','[]','approved','verified','verified','now','now')"
        )
        ui = self.ui()
        user = self.update(77, "/status")
        await ui.command(user, None)
        response = self.last_message().args[1]
        self.assertIn("self-service access available", response.lower())
        self.assertNotIn("req-88", response)
        self.assertNotIn("other", response)

        admin = self.update(42, "/faq set education | The approved education FAQ text.")
        await ui.command(admin, None)
        self.assertIn("updated", self.last_message().args[1].lower())
        user.message.text = "Tell me about education lessons"
        await ui.text(user, None)
        self.assertIn("The approved education FAQ text.", self.last_message().args[1])
        with self.assertRaises(PermissionError):
            await ui.command(self.update(77, "/assistant off"), None)

    async def test_rate_limit_unknown_repeats_and_pausing_keeps_membership_commands(self):
        ui = self.ui()
        user = self.update(77, "hello")
        await ui.text(user, None)
        user.message.text = "hello"
        await ui.text(user, None)
        self.assertIn("same message", self.last_message().args[1].lower())

        admin = self.update(42, "/assistant off")
        await ui.command(admin, None)
        self.assertFalse(ui.assistant_enabled())
        paused_user = self.update(88, "Tell me about lessons")
        await ui.text(paused_user, None)
        self.assertIn("temporarily paused", self.last_message().args[1])
        paused_user.message.text = "/apply"
        await ui.command(paused_user, None)
        self.assertIn("Choose", self.last_message().args[1])

    async def test_admin_can_set_private_member_notice_for_paused_assistant(self):
        ui = self.ui()
        admin = self.update(42)
        with self.assertRaises(PermissionError):
            await ui.assistant_inactive_notice_prompt(self.update(77))

        await ui.assistant_inactive_notice_prompt(admin)
        self.assertIn("reason members should see", self.last_message().args[1].lower())
        admin.message.text = "Automated replies are paused for scheduled maintenance until 6 PM."
        await ui.text(admin, None)
        self.assertEqual(
            self.db.get("assistant:inactive_reason"),
            "Automated replies are paused for scheduled maintenance until 6 PM.",
        )
        self.assertIsNone(self.db.get(ui.assistant_inactive_notice_pending_key(42)))

        admin.message.text = "/assistant off"
        await ui.command(admin, None)
        member = self.update(77, "Hello")
        await ui.text(member, None)
        reply = self.last_message()
        self.assertIn("Automated replies are temporarily paused.", reply.args[1])
        self.assertIn("Reason: Automated replies are paused for scheduled maintenance until 6 PM.",
                      reply.args[1])
        labels = [button.text for row in reply.kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertIn("🔐 Member Access", labels)
        self.assertIn("🔎 My Access / Status", labels)
        self.assertIn("💬 Contact Administrator", labels)
        self.assertTrue(all(call.args[0] not in (-1001, -1002)
                            for call in self.bot.send_message.await_args_list))

    async def test_paused_reason_is_in_start_reply_and_can_be_reset(self):
        ui = self.ui()
        self.db.put("assistant:enabled", False)
        self.db.put("assistant:inactive_reason", "The administrator is reviewing the service.")
        await ui.command(self.update(77, "/start"), None)
        self.assertIn("The administrator is reviewing the service.", self.last_message().args[1])

        await ui.assistant_inactive_notice_reset(self.update(42))
        self.assertIsNone(self.db.get("assistant:inactive_reason"))
        self.assertEqual(ui.assistant_inactive_reason(), DEFAULT_INACTIVE_REASON)

    async def test_admin_reply_is_private_and_uncertain_delivery_is_never_retried(self):
        ui = self.ui()
        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('case-1',77,'Question','open','now','now')"
        )
        admin = self.update(42, "/reply case-1 Please check /status for the current result.")
        await ui.command(admin, None)
        self.assertEqual(self.bot.send_message.await_args_list[0].args[0], 77)
        self.assertIn(
            "💬 VAYDA | Administrator · Administrator",
            self.bot.send_message.await_args_list[0].args[1],
        )
        self.assertEqual(
            self.db.rows("SELECT status FROM assistant_escalations WHERE id='case-1'")[0]["status"],
            "replied",
        )

        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('case-2',77,'Another question','open','now','now')"
        )
        async def uncertain_member_delivery(chat_id, *args, **kwargs):
            if chat_id == 77:
                raise TimeoutError("simulated timeout")
            return NS(message_id=90)

        self.bot.send_message.side_effect = uncertain_member_delivery
        admin.message.text = "/reply case-2 Please try /status."
        await ui.command(admin, None)
        self.assertEqual(
            self.db.rows("SELECT status FROM assistant_escalations WHERE id='case-2'")[0]["status"],
            "reply_uncertain",
        )
        sent_before = self.bot.send_message.await_count
        with self.assertRaises(ValueError):
            await ui.command(admin, None)
        self.assertEqual(self.bot.send_message.await_count, sent_before)
        self.assertTrue(all(call.args[0] not in (-1001, -1002)
                            for call in self.bot.send_message.await_args_list))

    async def test_support_case_details_redirect_to_portal_in_admin_telegram(self):
        ui = self.ui()
        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('case-button',77,'Question from a member','open','now','now')"
        )
        admin = self.update(42)
        await ui.assistant_admin_panel(admin)
        self.assertIn("Support Portal", self.last_message().args[1])
        await ui.assistant_queue(admin)
        queue_text = self.last_message().args[1]
        self.assertIn("Support Portal", queue_text)
        self.assertNotIn("Question from a member", queue_text)

        await ui.assistant_case(admin, "case-button")
        case_text = self.last_message().args[1]
        self.assertIn("Support Portal", case_text)
        self.assertNotIn("Question from a member", case_text)
        self.assertFalse(any(call.args[0] == 77 for call in self.bot.send_message.await_args_list))

    async def test_reply_button_delivery_timeout_is_uncertain_and_not_retried(self):
        ui = self.ui()
        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('case-timeout-button',77,'Question','open','now','now')"
        )
        async def uncertain_member_delivery(chat_id, *args, **kwargs):
            if chat_id == 77:
                raise TimeoutError("simulated timeout")
            return NS(message_id=90)

        self.bot.send_message.side_effect = uncertain_member_delivery
        admin = self.update(42, "/reply case-timeout-button Please try again later.")
        await ui.command(admin, None)
        self.assertEqual(self.db.rows(
            "SELECT status FROM assistant_escalations WHERE id='case-timeout-button'")[0]["status"],
            "reply_uncertain")
        self.assertIsNone(self.db.get("assistant:reply_pending:42"))
        sent_to_member = sum(call.args[0] == 77 for call in self.bot.send_message.await_args_list)
        self.assertEqual(sent_to_member, 1)

        admin.message.text = "This must not retry automatically."
        await ui.text(admin, None)
        self.assertEqual(
            sum(call.args[0] == 77 for call in self.bot.send_message.await_args_list), sent_to_member)

    async def test_reply_button_is_restricted_to_admin_and_can_be_cancelled(self):
        ui = self.ui()
        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('case-cancel-button',77,'Question','open','now','now')"
        )
        with self.assertRaises(PermissionError):
            await ui.assistant_reply_start(self.update(77), "case-cancel-button")

        admin = self.update(42)
        await ui.assistant_reply_start(admin, "case-cancel-button")
        self.assertEqual(self.db.get("assistant:reply_pending:42"), "case-cancel-button")
        admin.message.text = "/cancel"
        await ui.command(admin, None)
        self.assertIsNone(self.db.get("assistant:reply_pending:42"))
        self.assertEqual(self.db.rows(
            "SELECT status FROM assistant_escalations WHERE id='case-cancel-button'")[0]["status"], "open")

    async def test_restart_recovers_contact_state_and_quarantines_uncertain_admin_reply(self):
        self.db.put("assistant:visited:77", True)
        self.db.put("assistant:contact_pending:77", True)
        self.db.save_draft(77, {
            "kind": "destination_application", "destination": "education",
            "answers": ["Beginner"], "step": "answers", "revision": 1,
        })
        self.db.execute(
            "INSERT INTO assistant_escalations(id,user_id,question,status,created,updated) "
            "VALUES ('case-3',77,'Saved request','reply_sending','now','now')"
        )
        directory = self.temp.name
        self.db.conn.close()
        self.db = Database(directory)
        ui = self.ui()
        self.assertTrue(self.db.get("assistant:contact_pending:77"))
        self.assertEqual(
            self.db.rows("SELECT status FROM assistant_escalations WHERE id='case-3'")[0]["status"],
            "reply_uncertain",
        )
        user = self.update(77, "/start")
        await ui.command(user, None)
        self.assertIn("WELCOME TO VAYDA SMART MONEY HUB", self.last_message().args[1])
        labels = [button.text for row in self.last_message().kwargs["reply_markup"].inline_keyboard
                  for button in row]
        self.assertIn("▶️ Continue my saved step", labels)
