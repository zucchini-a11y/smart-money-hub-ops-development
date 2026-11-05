import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from smh.database import Database, now
from smh.pro_review_worker import (
    process_review_command,
    recover_interrupted_commands,
    run_portal_member_review_worker,
)


class FakeReviewUI:
    def __init__(self, db):
        self.db = db
        self.messages = []
        self.raise_on_load = False

    def member_request(self, request_id):
        if self.raise_on_load:
            raise TimeoutError("synthetic local reload timeout")
        rows = self.db.rows("SELECT * FROM member_requests WHERE id=?", (request_id,))
        return rows[0] if rows else None

    async def send_pro_outcome(self, request, status, decision_note=None):
        self.messages.append(("outcome", dict(request), status, decision_note))
        return True

    async def send_portal_funding_evidence_request(self, request, reason):
        self.messages.append(("evidence", dict(request), reason))
        return True

    async def send_portal_pro_registration_notice(self, user, reason="", request_id=None):
        self.messages.append(("registration_approved", user, reason, request_id))
        return True

    async def send_portal_pro_registration_rejected_notice(self, user, reason=""):
        self.messages.append(("registration_rejected", user, reason))
        return True

    async def send_portal_funding_verified_notice(self, user, *, registration_approved, reason=""):
        self.messages.append(("funding_verified", user, registration_approved, reason))
        return True

    async def send_portal_funding_rejected_notice(self, user, reason=""):
        self.messages.append(("funding_rejected", user, reason))
        return True

    async def send_portal_pro_approval_notice(self, user, invite_link=None):
        self.messages.append(("approval", user, invite_link))
        return True


class FakePublisher:
    def __init__(self, db):
        self.db = db
        self.prepare_calls = []
        self.send_calls = []
        self.fail_send = False

    def prepare(self, actor, kind, payload):
        self.prepare_calls.append((actor, kind, payload))
        operation_id = f"op-{len(self.prepare_calls)}"
        stamp = now()
        self.db.execute(
            "INSERT INTO operations(id,kind,payload,status,message_id,created,updated) "
            "VALUES (?,?,?,'prepared',NULL,?,?)",
            (operation_id, kind, json.dumps(payload), stamp, stamp),
        )
        return operation_id

    async def send(self, actor, operation_id):
        self.send_calls.append((actor, operation_id))
        if self.fail_send:
            raise TimeoutError("synthetic Telegram timeout")
        self.db.execute("UPDATE operations SET status='done',updated=? WHERE id=?",
                        (now(), operation_id))
        _row, payload = self.operation(operation_id)
        self.db.execute(
            "UPDATE access SET status='invite_issued',updated=? WHERE user_id=? AND channel=?",
            (now(), payload["user"], payload["channel"]),
        )
        self.db.put(f"invite:{operation_id}", {
            "invite_link": "https://t.me/+private-test-invite"
        })

    def operation(self, operation_id):
        row = self.db.rows("SELECT * FROM operations WHERE id=?", (operation_id,))[0]
        return row, json.loads(row["payload"])


class PortalProReviewWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "data")
        self.ui = FakeReviewUI(self.db)
        self.publisher = FakePublisher(self.db)
        self.config = SimpleNamespace(
            isolated_test=True, database_schema="smh_test", admin=999, signals=-100123
        )

    def tearDown(self):
        self.db.conn.close()
        self.temp.cleanup()

    def add_application(self, *, status="pending_review", registration="verified",
                        funding="verified", request_id="request-1", user_id=4242):
        stamp = now()
        self.db.execute(
            "INSERT INTO member_requests "
            "(id,user_id,destination,answers,status,registration_status,funding_status,created,updated) "
            "VALUES (?,?, 'pro','{}', ?,?,?,?,?)",
            (request_id, user_id, status, registration, funding, stamp, stamp),
        )
        return stamp

    def add_command(self, request_stamp, *, action="approve", command_id="command-1",
                    reason="Reviewed in the Development test"):
        stamp = now()
        self.db.execute(
            "INSERT INTO portal_member_review_commands "
            "(id,request_id,actor_id,action,previous_status,previous_funding_status,"
            "expected_updated,reason,idempotency_key,command_status,delivery_status,created,updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,'queued','not_attempted',?,?)",
            (command_id, "request-1", "portal-owner-test", action, "pending_review",
             "pending_review", request_stamp, reason, f"idem-{command_id}", stamp, stamp),
        )
        return command_id

    async def test_verified_approval_creates_one_invite_and_notifies_with_hidden_link_value(self):
        request_stamp = self.add_application()
        self.add_command(request_stamp)

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        self.assertFalse(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))

        application = self.db.rows("SELECT status,admin_decision_by FROM member_requests")[0]
        self.assertEqual(application["status"], "approved")
        self.assertEqual(application["admin_decision_by"], 999)
        access = self.db.rows("SELECT status FROM access WHERE user_id=4242 AND channel=-100123")[0]
        self.assertEqual(access["status"], "invite_issued")
        self.assertEqual(self.db.rows("SELECT command_status,delivery_status FROM "
                                     "portal_member_review_commands")[0]["command_status"], "completed")
        self.assertEqual(len(self.publisher.prepare_calls), 1)
        self.assertEqual(len(self.publisher.send_calls), 1)
        self.assertEqual(len(self.ui.messages), 1)
        self.assertEqual(self.ui.messages[0][0], "approval")
        self.assertEqual(self.ui.messages[0][2], "https://t.me/+private-test-invite")
        self.assertEqual(self.db.rows("SELECT action FROM member_request_events")[0]["action"],
                         "portal_pro_approve")

    async def test_registration_approval_unlocks_education_only_without_channel_invite(self):
        request_stamp = self.add_application(registration="pending_review", funding="not_submitted")
        self.add_command(request_stamp, action="approve_registration")

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))

        request = self.db.rows("SELECT status,registration_status,funding_status FROM member_requests")[0]
        self.assertEqual(request["status"], "pending_review")
        self.assertEqual(request["registration_status"], "approved")
        self.assertEqual(request["funding_status"], "not_submitted")
        self.assertEqual(self.db.rows("SELECT * FROM access"), [])
        self.assertEqual(self.publisher.prepare_calls, [])
        self.assertEqual(self.publisher.send_calls, [])
        self.assertEqual(self.ui.messages[0][0], "registration_approved")
        self.assertEqual(self.ui.messages[0][3], "request-1")

    async def test_verified_funding_after_registration_approval_issues_one_isolated_invite(self):
        request_stamp = self.add_application(
            registration="approved", funding="pending_review")
        self.db.execute(
            "UPDATE member_requests SET evidence_file_id='synthetic-evidence' WHERE id='request-1'"
        )
        self.add_command(request_stamp, action="verify_funding")

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))

        request = self.db.rows("SELECT status,registration_status,funding_status FROM member_requests")[0]
        self.assertEqual((request["status"], request["registration_status"], request["funding_status"]),
                         ("approved", "approved", "verified"))
        access = self.db.rows("SELECT status FROM access WHERE user_id=4242 AND channel=-100123")[0]
        self.assertEqual(access["status"], "invite_issued")
        self.assertEqual(len(self.publisher.send_calls), 1)

    async def test_funding_verification_without_registration_approval_cannot_issue_channel_invite(self):
        request_stamp = self.add_application(
            registration="pending_review", funding="pending_review")
        self.db.execute(
            "UPDATE member_requests SET evidence_file_id='synthetic-evidence' WHERE id='request-1'"
        )
        self.add_command(request_stamp, action="verify_funding")

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))

        request = self.db.rows("SELECT registration_status,funding_status FROM member_requests")[0]
        self.assertEqual((request["registration_status"], request["funding_status"]),
                         ("pending_review", "verified"))
        self.assertEqual(self.db.rows("SELECT * FROM access"), [])
        self.assertEqual(self.publisher.send_calls, [])
        self.assertEqual(self.ui.messages[0][0], "funding_verified")
        self.assertFalse(self.ui.messages[0][2])

    async def test_registration_approval_after_funding_verification_grants_channel_access(self):
        request_stamp = self.add_application(
            registration="pending_review", funding="pending_review")
        self.db.execute(
            "UPDATE member_requests SET evidence_file_id='synthetic-evidence' WHERE id='request-1'"
        )
        self.add_command(request_stamp, action="verify_funding", command_id="command-funding")
        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-funding"))
        self.assertEqual(self.publisher.send_calls, [])

        after_funding = self.db.rows("SELECT updated FROM member_requests WHERE id='request-1'")[0]["updated"]
        self.add_command(after_funding, action="approve_registration", command_id="command-registration")
        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-registration"))

        request = self.db.rows("SELECT status,registration_status,funding_status FROM member_requests")[0]
        self.assertEqual((request["status"], request["registration_status"], request["funding_status"]),
                         ("approved", "approved", "verified"))
        access = self.db.rows("SELECT status FROM access WHERE user_id=4242 AND channel=-100123")[0]
        self.assertEqual(access["status"], "invite_issued")
        self.assertEqual(len(self.publisher.send_calls), 1)
        self.assertEqual(self.ui.messages[-1][0], "approval")

    async def test_registration_rejection_closes_education_eligibility_without_inviting(self):
        request_stamp = self.add_application(registration="pending_review", funding="not_submitted")
        self.add_command(request_stamp, action="reject_registration")

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))

        request = self.db.rows("SELECT status,registration_status FROM member_requests")[0]
        self.assertEqual((request["status"], request["registration_status"]), ("rejected", "rejected"))
        self.assertEqual(self.db.rows("SELECT * FROM access"), [])
        self.assertEqual(self.publisher.send_calls, [])
        self.assertEqual(self.ui.messages[0][0], "registration_rejected")

    async def test_funding_rejection_keeps_registration_education_only(self):
        request_stamp = self.add_application(
            registration="approved", funding="pending_review")
        self.db.execute(
            "UPDATE member_requests SET evidence_file_id='synthetic-evidence' WHERE id='request-1'"
        )
        self.add_command(request_stamp, action="reject_funding")

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))

        request = self.db.rows("SELECT status,registration_status,funding_status FROM member_requests")[0]
        self.assertEqual((request["status"], request["registration_status"], request["funding_status"]),
                         ("pending_review", "approved", "rejected"))
        self.assertEqual(self.db.rows("SELECT * FROM access"), [])
        self.assertEqual(self.publisher.send_calls, [])
        self.assertEqual(self.ui.messages[0][0], "funding_rejected")

    async def test_rejection_is_blocked_while_verification_is_pending(self):
        request_stamp = self.add_application(registration="pending_review")
        self.add_command(request_stamp, action="reject")

        self.assertFalse(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        self.assertEqual(self.db.rows("SELECT status FROM member_requests")[0]["status"], "pending_review")
        self.assertEqual(self.db.rows("SELECT command_status FROM "
                                     "portal_member_review_commands")[0]["command_status"], "stale")
        self.assertEqual(self.ui.messages, [])
        self.assertEqual(self.publisher.send_calls, [])

    async def test_rejection_notice_uses_rejected_status_and_owner_reason(self):
        request_stamp = self.add_application(registration="verified", funding="verified")
        self.add_command(request_stamp, action="reject", reason="Please update your registration details.")

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        sent_request = self.ui.messages[0][1]
        self.assertEqual(sent_request["status"], "rejected")
        self.assertEqual(sent_request["followup_text"], "Please update your registration details.")
        self.assertEqual(self.ui.messages[0][2], "REJECTED")
        self.assertEqual(self.publisher.prepare_calls, [])

    async def test_requesting_updated_evidence_keeps_approved_access_active(self):
        request_stamp = self.add_application(status="approved")
        self.db.execute("INSERT INTO applications VALUES (4242,'[]','destination_applicant',?)",
                        (request_stamp,))
        self.db.execute("INSERT INTO access VALUES (4242,-100123,'joined',?)", (request_stamp,))
        self.add_command(request_stamp, action="request_evidence")

        self.assertTrue(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        request = self.db.rows("SELECT status,funding_status FROM member_requests")[0]
        self.assertEqual(request["status"], "approved")
        self.assertEqual(request["funding_status"], "evidence_requested")
        self.assertEqual(self.db.rows("SELECT status FROM access")[0]["status"], "joined")
        self.assertEqual(self.ui.messages[0][0], "evidence")
        self.assertEqual(self.publisher.send_calls, [])

    async def test_uncertain_invite_send_is_quarantined_and_never_retried(self):
        request_stamp = self.add_application()
        self.add_command(request_stamp)
        self.publisher.fail_send = True

        self.assertFalse(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        self.assertFalse(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        self.assertEqual(len(self.publisher.send_calls), 1)
        command = self.db.rows("SELECT command_status,delivery_status FROM "
                               "portal_member_review_commands")[0]
        self.assertEqual((command["command_status"], command["delivery_status"]),
                         ("uncertain", "uncertain"))

    async def test_restart_quarantines_processing_command_without_replaying(self):
        request_stamp = self.add_application()
        self.add_command(request_stamp)
        self.db.execute(
            "UPDATE portal_member_review_commands SET command_status='processing' WHERE id='command-1'"
        )

        recover_interrupted_commands(self.db)
        self.assertFalse(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        self.assertEqual(self.db.rows("SELECT command_status FROM "
                                     "portal_member_review_commands")[0]["command_status"], "uncertain")
        self.assertEqual(self.publisher.send_calls, [])
        self.assertEqual(self.ui.messages, [])

    async def test_application_reload_error_is_quarantined_without_retry(self):
        request_stamp = self.add_application()
        self.add_command(request_stamp)
        self.ui.raise_on_load = True

        self.assertFalse(await process_review_command(
            self.db, self.ui, self.publisher, self.config, "command-1"))
        self.assertEqual(self.db.rows("SELECT command_status FROM "
                                     "portal_member_review_commands")[0]["command_status"], "uncertain")
        self.assertEqual(self.publisher.send_calls, [])

    async def test_worker_refuses_non_isolated_configuration(self):
        production_config = SimpleNamespace(
            isolated_test=False, database_schema="smh", admin=999, signals=-100123
        )
        stop = asyncio.Event()
        stop.set()
        await run_portal_member_review_worker(
            self.db, self.ui, self.publisher, production_config, stop, interval=0
        )
        self.assertEqual(self.db.rows("SELECT command_status FROM "
                                     "portal_member_review_commands"), [])
        self.assertEqual(self.publisher.send_calls, [])

    async def test_worker_publishes_short_lived_readiness_heartbeat_after_recovery(self):
        stop = asyncio.Event()
        worker = asyncio.create_task(run_portal_member_review_worker(
            self.db, self.ui, self.publisher, self.config, stop, interval=0.05
        ))
        for _ in range(20):
            if self.db.get("portal_pro_review_worker_status"):
                break
            await asyncio.sleep(0.01)
        heartbeat = self.db.get("portal_pro_review_worker_status")
        self.assertEqual(heartbeat["version"], "pro-review-v1")
        self.assertEqual(heartbeat["status"], "ready")
        self.assertIsInstance(heartbeat["updated"], str)
        self.assertEqual(self.publisher.send_calls, [])
        stop.set()
        await worker
        self.assertEqual(self.db.get("portal_pro_review_worker_status")["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
