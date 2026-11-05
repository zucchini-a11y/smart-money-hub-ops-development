import json
import asyncio
import tempfile
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

from smh.applicant_followups import (
    ApplicantFollowupService,
    get_settings,
    followup_schema_available,
    mark_notice_shown,
    record_applicant_activity,
    run_applicant_followup_worker,
    set_followup_status,
    sending_is_enabled,
)
from smh.config import Config
from smh.database import Database, now
from smh.gemini_analysis import GeminiAnalysisError, generate_applicant_followup


class ApplicantFollowupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(self.temp.name)
        self.config = Config("test-token", 42, -1001, -1002, Path(self.temp.name))
        self.config = replace(
            self.config,
            education_group_id=-1003,
            education_link="https://t.me/+example",
            applicant_followups_enabled=False,
        )
        self.bot = NS(
            send_message=AsyncMock(return_value=NS(message_id=77)),
            get_chat_member=AsyncMock(return_value=NS(status="left")),
        )
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    def make_due(self, user_id=1001, stage="welcome", destination=None):
        record_applicant_activity(
            self.db, self.config, user_id, stage, destination)
        self.db.execute(
            "UPDATE applicant_followup_state SET next_followup=? WHERE user_id=?",
            (now(), user_id),
        )
        return self.service.state(user_id)

    def enable_admin_gate(self, categories=None):
        values = {
            "enabled": True,
            "reviewed": True,
            "sample_reviewed": True,
        }
        if categories is not None:
            values["categories"] = categories
        self.service.save_settings(values)

    async def test_environment_gate_defaults_off_even_if_admin_gate_is_set(self):
        self.enable_admin_gate(["welcome"])
        state = self.make_due()
        mark_notice_shown(self.db, 1001)
        await self.service.process_due(state)
        self.bot.send_message.assert_not_awaited()
        self.bot.get_chat_member.assert_not_awaited()
        self.assertFalse(sending_is_enabled(self.config, get_settings(self.db)))

    async def test_v8_database_skips_followup_hooks_without_querying_missing_tables(self):
        for table in (
            "applicant_followup_state",
            "applicant_followup_deliveries",
            "applicant_followup_events",
        ):
            self.db.execute(f"DROP TABLE {table}")
        self.db.conn.execute("PRAGMA user_version=8")

        self.assertFalse(followup_schema_available(self.db))
        self.assertIsNone(record_applicant_activity(self.db, self.config, 1001))
        self.assertIsNone(mark_notice_shown(self.db, 1001))
        self.assertIsNone(set_followup_status(self.db, 1001, "paused"))
        self.bot.send_message.assert_not_awaited()

    async def test_worker_waits_for_shutdown_when_schema_is_not_migrated(self):
        for table in (
            "applicant_followup_state",
            "applicant_followup_deliveries",
            "applicant_followup_events",
        ):
            self.db.execute(f"DROP TABLE {table}")
        self.db.conn.execute("PRAGMA user_version=8")
        stop = asyncio.Event()

        task = asyncio.create_task(
            run_applicant_followup_worker(self.db, self.config, self.bot, stop))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.bot.send_message.assert_not_awaited()

        stop.set()
        await asyncio.wait_for(task, timeout=1)

    async def test_welcome_reminder_is_private_and_schedule_is_persisted(self):
        self.config = replace(self.config, applicant_followups_enabled=True)
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)
        self.enable_admin_gate(["welcome"])
        state = self.make_due()
        mark_notice_shown(self.db, 1001)
        with patch("smh.applicant_followups.generate_applicant_followup",
                   return_value="If you would like to continue, choose the option below.") as generate:
            await self.service.process_due(state)
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.await_args.kwargs["chat_id"], 1001)
        self.assertIn("Stop Reminders", [
            button.text
            for row in self.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ])
        generate.assert_called_once()
        saved = self.service.state(1001)
        self.assertEqual(saved["reminders_sent"], 1)
        self.assertEqual(saved["status"], "active")
        self.assertIsNotNone(saved["next_followup"])
        deliveries = self.service.deliveries(1001)
        self.assertEqual([row["status"] for row in deliveries], ["sent"])

    async def test_membership_api_failure_never_sends_a_claim(self):
        self.config = replace(self.config, applicant_followups_enabled=True)
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)
        self.enable_admin_gate()
        self.bot.get_chat_member.side_effect = RuntimeError("private transport detail")
        state = self.make_due(stage="membership_check", destination="analysis")
        mark_notice_shown(self.db, 1001)
        with patch("smh.applicant_followups.generate_applicant_followup") as generate:
            await self.service.process_due(state)
        self.bot.send_message.assert_not_awaited()
        generate.assert_not_called()
        saved = self.service.state(1001)
        self.assertEqual(saved["status"], "active")
        self.assertIn("membership_unverifiable", saved["last_error"])

    async def test_pending_review_pauses_followup_until_admin_action(self):
        self.config = replace(self.config, applicant_followups_enabled=True)
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)
        self.enable_admin_gate()
        state = self.make_due(stage="application_draft", destination="analysis")
        mark_notice_shown(self.db, 1001)
        timestamp = now()
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,username,destination,answers,status,registration_status,funding_status,"
            "source,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("request-1", 1001, "", "analysis", "[]", "pending_review",
             "not_required", "not_required", "new", timestamp, timestamp),
        )
        await self.service.process_due(state)
        self.bot.get_chat_member.assert_not_awaited()
        self.bot.send_message.assert_not_awaited()
        saved = self.service.state(1001)
        self.assertEqual(saved["status"], "paused")
        self.assertEqual(saved["pause_reason"], "awaiting_admin_review")

    async def test_repeated_stage_activity_does_not_push_schedule_forward(self):
        state = self.make_due(stage="application_draft", destination="analysis")
        fixed_anchor = "2026-01-01T00:00:00+00:00"
        fixed_due = "2026-01-03T00:00:00+00:00"
        self.db.execute(
            "UPDATE applicant_followup_state SET schedule_anchor=?,next_followup=? WHERE user_id=?",
            (fixed_anchor, fixed_due, state["user_id"]),
        )
        record_applicant_activity(
            self.db, self.config, 1001, "application_draft", "analysis",
            source="repeated_answer")
        current = self.service.state(1001)
        self.assertEqual(current["schedule_anchor"], fixed_anchor)
        self.assertEqual(current["next_followup"], fixed_due)

    async def test_member_opt_out_stops_even_an_overdue_reminder(self):
        self.config = replace(self.config, applicant_followups_enabled=True)
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)
        self.enable_admin_gate(["welcome"])
        state = self.make_due()
        mark_notice_shown(self.db, 1001)
        set_followup_status(self.db, 1001, "opted_out", "member_requested_stop")
        await self.service.process_due(state)
        self.bot.send_message.assert_not_awaited()
        self.assertEqual(self.service.state(1001)["status"], "opted_out")

    async def test_due_reminder_waits_until_notice_is_shown(self):
        self.config = replace(self.config, applicant_followups_enabled=True)
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)
        self.enable_admin_gate(["welcome"])
        state = self.make_due()
        await self.service.process_due(state)
        self.bot.send_message.assert_not_awaited()
        saved = self.service.state(1001)
        self.assertEqual(saved["status"], "paused")
        self.assertEqual(saved["pause_reason"], "notice_not_seen")

    def test_welcome_nudges_are_not_enabled_by_default(self):
        self.assertNotIn("welcome", get_settings(self.db)["categories"])

    async def test_manual_draft_can_only_be_sent_once_and_only_with_both_gates(self):
        self.config = replace(self.config, applicant_followups_enabled=True)
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)
        self.enable_admin_gate(["welcome"])
        record_applicant_activity(self.db, self.config, 1001, "welcome")
        mark_notice_shown(self.db, 1001)
        draft = self.service.create_manual_draft(
            1001, "welcome", "If you want to continue, use the private access button.", 42)
        self.assertEqual(await self.service.send_delivery(draft["id"], manual=True), "sent")
        with self.assertRaisesRegex(ValueError, "not safely retryable"):
            await self.service.send_delivery(draft["id"], manual=True)
        self.bot.send_message.assert_awaited_once()

    async def test_ambiguous_telegram_failure_is_quarantined_not_replayed(self):
        self.config = replace(self.config, applicant_followups_enabled=True)
        self.service = ApplicantFollowupService(self.db, self.config, self.bot)
        self.enable_admin_gate(["welcome"])
        record_applicant_activity(self.db, self.config, 1001, "welcome")
        mark_notice_shown(self.db, 1001)
        draft = self.service.create_manual_draft(
            1001, "welcome", "A neutral private follow-up.", 42)
        self.bot.send_message.side_effect = RuntimeError("connection dropped")
        self.assertEqual(await self.service.send_delivery(draft["id"], manual=True), "uncertain")
        self.assertEqual(self.service.deliveries(1001)[0]["status"], "uncertain")
        with self.assertRaisesRegex(ValueError, "not safely retryable"):
            await self.service.send_delivery(draft["id"], manual=True)
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.service.state(1001)["pause_reason"], "uncertain_delivery")

    def test_gemini_prompt_uses_only_minimum_context_and_never_logs_key(self):
        payload = {
            "candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": "If you would like to continue, use Member Access."}]},
            }],
        }
        response = BytesIO(b"data: " + json.dumps(payload).encode() + b"\n\n")
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            return response

        result = generate_applicant_followup(
            {
                "user_id": 123456,
                "category": "welcome",
                "stage": "welcome",
                "destinations": ["Educational Group"],
                "next_action": "Open Member Access.",
                "private_answers": "must not be sent",
            },
            api_key="test-gemini-key",
            opener=opener,
            model="gemini-3.5-flash",
        )
        self.assertIn("Member Access", result)
        request_body = json.loads(captured["request"].data)
        prompt = request_body["contents"][0]["parts"][0]["text"]
        self.assertNotIn("123456", prompt)
        self.assertNotIn("must not be sent", prompt)
        self.assertNotIn("test-gemini-key", prompt)
        self.assertIn("gemini-3.5-flash", captured["request"].full_url)

    def test_gemini_auth_error_is_safe_and_does_not_reveal_key(self):
        error_payload = json.dumps({
            "error": {"status": "UNAUTHENTICATED", "message": "invalid API key"}
        }).encode()

        def opener(request, timeout):
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, BytesIO(error_payload))

        with self.assertRaises(GeminiAnalysisError) as caught:
            generate_applicant_followup(
                {"category": "welcome", "stage": "welcome", "destinations": [],
                 "next_action": "Open Member Access."},
                api_key="test-gemini-key",
                opener=opener,
            )
        self.assertIn("authentication failed", str(caught.exception).lower())
        self.assertNotIn("test-gemini-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
