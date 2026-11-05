"""Process portal-issued PRO review decisions only in the isolated test bot."""
import asyncio
import logging
import re
import time
from .database import now
from .portal_review_policy import may_process_review_action

log = logging.getLogger("smh")
_WORKER_STATUS_KEY = "portal_pro_review_worker_status"
_WORKER_VERSION = "pro-review-v1"
_HEARTBEAT_SECONDS = 20
_ERROR_LOG_SECONDS = 30

_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(password|passcode|otp|one[- ]time code|recovery code|private key|access token)\s*[:=]"
)
_ACTIVE_ACCESS_STATES = {"joined", "member", "administrator", "creator", "invite_issued"}
_UNSAFE_EXISTING_INVITE_STATES = {"invite_pending", "invite_uncertain", "disapproval_pending"}


def _write_worker_status(db, status):
    db.put(_WORKER_STATUS_KEY, {
        "version": _WORKER_VERSION,
        "status": status,
        "updated": now(),
    })


def recover_interrupted_commands(db):
    """Quarantine claimed commands after process death; never replay their side effects."""
    stamp = now()
    with db.transaction() as cursor:
        cursor.execute(
            "UPDATE portal_member_review_commands "
            "SET command_status='uncertain',"
            "delivery_status=CASE WHEN delivery_status='not_attempted' THEN 'uncertain' ELSE delivery_status END,"
            "safe_result=?,updated=?,completed_at=? WHERE command_status='processing'",
            ("The worker stopped after claiming this review. Check the member status and Telegram history before acting again.",
             stamp, stamp),
        )


def _complete(db, command_id, status, delivery_status, safe_result):
    stamp = now()
    db.execute(
        "UPDATE portal_member_review_commands SET command_status=?,delivery_status=?,safe_result=?,"
        "updated=?,completed_at=? WHERE id=? AND command_status='processing'",
        (status, delivery_status, safe_result[:500], stamp, stamp, command_id),
    )


def _claim_and_apply(db, command_id, admin_id, signals_channel):
    """Atomically claim the command and apply its database decision before any Telegram call."""
    stamp = now()
    with db.transaction() as cursor:
        command = cursor.execute(
            "SELECT * FROM portal_member_review_commands WHERE id=?", (command_id,)
        ).fetchone()
        if not command or command["command_status"] != "queued":
            return None
        application = cursor.execute(
            "SELECT * FROM member_requests WHERE id=? AND destination='pro'",
            (command["request_id"],),
        ).fetchone()
        if not application:
            cursor.execute(
                "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                "WHERE id=? AND command_status='queued'",
                ("The PRO application no longer exists.", stamp, stamp, command_id),
            )
            return None
        if str(application["updated"]) != str(command["expected_updated"]) or \
                not may_process_review_action(application, command["action"]):
            cursor.execute(
                "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                "WHERE id=? AND command_status='queued'",
                ("The application changed or no longer meets the selected decision requirements.",
                 stamp, stamp, command_id),
            )
            return None
        reason = str(command["reason"] or "").strip()
        if not reason or _CREDENTIAL_PATTERN.search(reason):
            cursor.execute(
                "UPDATE portal_member_review_commands SET command_status='failed',safe_result=?,updated=?,completed_at=? "
                "WHERE id=? AND command_status='queued'",
                ("The review note was empty or appeared to contain credentials; no member message was sent.",
                 stamp, stamp, command_id),
            )
            return None

        action = command["action"]
        user_id = application["user_id"]
        previous_access = None
        registration_approved = application["registration_status"] in ("approved", "verified")
        grant_channel_access = False
        if action == "approve_registration":
            updated = cursor.execute(
                "UPDATE member_requests SET registration_status='approved',"
                "status=CASE WHEN status IN ('pending_review','legacy_review') AND "
                "funding_status='verified' THEN 'approved' ELSE status END,"
                "admin_decision_by=CASE WHEN status IN ('pending_review','legacy_review') AND "
                "funding_status='verified' THEN ? ELSE admin_decision_by END,"
                "admin_decision_at=CASE WHEN status IN ('pending_review','legacy_review') AND "
                "funding_status='verified' THEN ? ELSE admin_decision_at END,"
                "followup_text=?,updated=? "
                "WHERE id=? AND destination='pro' AND status IN ('pending_review','legacy_review') "
                "AND registration_status IN ('pending_review','unverified')",
                (admin_id, stamp, reason, stamp, command["request_id"]),
            )
            if updated.rowcount != 1:
                cursor.execute(
                    "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                    "WHERE id=?",
                    ("Registration status changed before approval could be recorded.", stamp, stamp, command_id),
                )
                return None
            grant_channel_access = (
                application["funding_status"] == "verified" and
                application["status"] != "approved"
            )
            if grant_channel_access:
                cursor.execute(
                    "INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
                    (user_id, "[]", "destination_applicant", stamp),
                )
                access = cursor.execute(
                    "SELECT status FROM access WHERE user_id=? AND channel=?",
                    (user_id, signals_channel),
                ).fetchone()
                previous_access = access[0] if access else None
                if not access:
                    cursor.execute(
                        "INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                        (user_id, signals_channel, "invite_pending", stamp),
                    )
        elif action == "reject_registration":
            updated = cursor.execute(
                "UPDATE member_requests SET registration_status='rejected',status='rejected',"
                "admin_decision_by=?,admin_decision_at=?,followup_text=?,updated=? "
                "WHERE id=? AND destination='pro' AND status IN ('pending_review','legacy_review') "
                "AND registration_status IN ('pending_review','unverified')",
                (admin_id, stamp, reason, stamp, command["request_id"]),
            )
            if updated.rowcount != 1:
                cursor.execute(
                    "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                    "WHERE id=?",
                    ("Registration status changed before rejection could be recorded.", stamp, stamp, command_id),
                )
                return None
        elif action == "verify_funding":
            updated = cursor.execute(
                "UPDATE member_requests SET funding_status='verified',followup_text=?,"
                "status=CASE WHEN status IN ('pending_review','legacy_review') AND "
                "registration_status IN ('approved','verified') THEN 'approved' ELSE status END,"
                "admin_decision_by=CASE WHEN status IN ('pending_review','legacy_review') AND "
                "registration_status IN ('approved','verified') THEN ? ELSE admin_decision_by END,"
                "admin_decision_at=CASE WHEN status IN ('pending_review','legacy_review') AND "
                "registration_status IN ('approved','verified') THEN ? ELSE admin_decision_at END,updated=? "
                "WHERE id=? AND destination='pro' AND funding_status='pending_review'",
                (reason, admin_id, stamp, stamp, command["request_id"]),
            )
            if updated.rowcount != 1:
                cursor.execute(
                    "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                    "WHERE id=?",
                    ("Funding verification changed before it could be recorded.", stamp, stamp, command_id),
                )
                return None
            grant_channel_access = registration_approved and application["status"] != "approved"
            if grant_channel_access:
                cursor.execute(
                    "INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
                    (user_id, "[]", "destination_applicant", stamp),
                )
                access = cursor.execute(
                    "SELECT status FROM access WHERE user_id=? AND channel=?",
                    (user_id, signals_channel),
                ).fetchone()
                previous_access = access[0] if access else None
                if not access:
                    cursor.execute(
                        "INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                        (user_id, signals_channel, "invite_pending", stamp),
                    )
        elif action == "reject_funding":
            updated = cursor.execute(
                "UPDATE member_requests SET funding_status='rejected',followup_text=?,updated=? "
                "WHERE id=? AND destination='pro' AND status!='approved' AND funding_status='pending_review'",
                (reason, stamp, command["request_id"]),
            )
            if updated.rowcount != 1:
                cursor.execute(
                    "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                    "WHERE id=?",
                    ("Funding review changed before rejection could be recorded.", stamp, stamp, command_id),
                )
                return None
        elif action == "approve":
            grant_channel_access = True
            access = cursor.execute(
                "SELECT status FROM access WHERE user_id=? AND channel=?",
                (user_id, signals_channel),
            ).fetchone()
            previous_access = access[0] if access else None
            updated = cursor.execute(
                "UPDATE member_requests SET status='approved',admin_decision_by=?,admin_decision_at=?,updated=? "
                "WHERE id=? AND destination='pro' AND status IN ('pending_review','legacy_review') "
                "AND registration_status IN ('approved','verified') AND funding_status='verified'",
                (admin_id, stamp, stamp, command["request_id"]),
            )
            if updated.rowcount != 1:
                cursor.execute(
                    "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                    "WHERE id=?",
                    ("The application changed before final approval could be recorded.", stamp, stamp, command_id),
                )
                return None
            cursor.execute(
                "INSERT OR IGNORE INTO applications VALUES (?,?,?,?)",
                (user_id, "[]", "destination_applicant", stamp),
            )
        elif action == "reject":
            updated = cursor.execute(
                "UPDATE member_requests SET status='rejected',admin_decision_by=?,admin_decision_at=?,"
                "followup_text=?,updated=? WHERE id=? AND destination='pro' "
                "AND status NOT IN ('approved','rejected','not_yet_eligible','revoked') "
                "AND registration_status!='pending_review' AND funding_status!='pending_review'",
                (admin_id, stamp, reason, stamp, command["request_id"]),
            )
            if updated.rowcount != 1:
                cursor.execute(
                    "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                    "WHERE id=?",
                    ("The application changed or verification is still pending; no rejection was recorded.",
                     stamp, stamp, command_id),
                )
                return None
        elif action == "request_evidence":
            if application["status"] == "approved":
                updated = cursor.execute(
                    "UPDATE member_requests SET funding_status='evidence_requested',followup_text=?,updated=? "
                    "WHERE id=? AND destination='pro' AND status='approved' "
                    "AND registration_status IN ('approved','verified') AND funding_status!='pending_review' "
                    "AND funding_status!='evidence_requested'",
                    (reason, stamp, command["request_id"]),
                )
            else:
                updated = cursor.execute(
                    "UPDATE member_requests SET status='information_requested',funding_status='evidence_requested',"
                    "followup_text=?,updated=? WHERE id=? AND destination='pro' "
                    "AND status IN ('pending_review','legacy_review','information_requested') "
                    "AND funding_status!='pending_review' AND funding_status!='evidence_requested'",
                    (reason, stamp, command["request_id"]),
                )
            if updated.rowcount != 1:
                cursor.execute(
                    "UPDATE portal_member_review_commands SET command_status='stale',safe_result=?,updated=?,completed_at=? "
                    "WHERE id=?",
                    ("The application changed before the evidence request could be recorded.", stamp, stamp, command_id),
                )
                return None
        else:
            return None

        cursor.execute(
            "INSERT INTO member_request_events(request_id,actor,action,detail,created) VALUES (?,?,?,?,?)",
            (command["request_id"], admin_id, f"portal_pro_{action}", reason[:400], stamp),
        )
        if action == "approve":
            access = cursor.execute(
                "SELECT status FROM access WHERE user_id=? AND channel=?",
                (user_id, signals_channel),
            ).fetchone()
            previous_access = access[0] if access else previous_access
            if not access:
                cursor.execute(
                    "INSERT OR REPLACE INTO access VALUES (?,?,?,?)",
                    (user_id, signals_channel, "invite_pending", stamp),
                )
        cursor.execute(
            "UPDATE portal_member_review_commands SET command_status='processing',delivery_status='not_attempted',"
            "attempt_count=attempt_count+1,updated=? WHERE id=? AND command_status='queued'",
            (stamp, command_id),
        )
        return {
            "command_id": str(command["id"]),
            "request_id": str(command["request_id"]),
            "action": str(action),
            "reason": reason,
            "user_id": user_id,
            "application": dict(application),
            "previous_access": previous_access,
            "grant_channel_access": grant_channel_access,
            "registration_approved": (
                action == "approve_registration" or
                registration_approved or
                action == "verify_funding" and registration_approved
            ),
        }


async def process_review_command(db, ui, publisher, config, command_id):
    """Process one queued command once. Telegram send outcomes are never blindly replayed."""
    work = _claim_and_apply(db, command_id, config.admin, config.signals)
    if not work:
        return False
    try:
        request = ui.member_request(work["request_id"])
        if not request:
            _complete(
                db, command_id, "uncertain", "uncertain",
                "The application could not be reloaded after the decision. Check its saved status before acting again.",
            )
            return False
        action = work["action"]
        if action == "reject":
            request = {**request, "status": "rejected", "followup_text": work["reason"]}
            delivered = await ui.send_pro_outcome(
                request, "REJECTED", decision_note=work["reason"])
            if delivered:
                _complete(db, command_id, "completed", "sent", "The applicant was notified privately.")
            else:
                _complete(db, command_id, "uncertain", "uncertain",
                          "Private notification delivery could not be confirmed; it will not be resent automatically.")
            return delivered
        if action == "request_evidence":
            delivered = await ui.send_portal_funding_evidence_request(request, work["reason"])
            if delivered:
                _complete(db, command_id, "completed", "sent", "The applicant was privately asked for updated evidence.")
            else:
                _complete(db, command_id, "uncertain", "uncertain",
                          "Private notification delivery could not be confirmed; it will not be resent automatically.")
            return delivered

        if action == "approve_registration" and not work["grant_channel_access"]:
            delivered = await ui.send_portal_pro_registration_notice(
                work["user_id"], work["reason"], request_id=work["request_id"])
            if delivered:
                _complete(
                    db, command_id, "completed", "sent",
                    "PRO education eligibility was approved. No PRO Signals access or invite was granted.",
                )
            else:
                _complete(db, command_id, "uncertain", "uncertain",
                          "Registration approval was saved; private notification delivery could not be confirmed.")
            return delivered

        if action == "reject_registration":
            delivered = await ui.send_portal_pro_registration_rejected_notice(work["user_id"], work["reason"])
            if delivered:
                _complete(db, command_id, "completed", "sent",
                          "Registration was rejected. Existing channel membership was not automatically removed.")
            else:
                _complete(db, command_id, "uncertain", "uncertain",
                          "Registration rejection was saved; private notification delivery could not be confirmed.")
            return delivered

        if action == "reject_funding":
            delivered = await ui.send_portal_funding_rejected_notice(work["user_id"], work["reason"])
            if delivered:
                _complete(db, command_id, "completed", "sent",
                          "Funding verification was rejected. No PRO Signals access was granted.")
            else:
                _complete(db, command_id, "uncertain", "uncertain",
                          "Funding rejection was saved; private notification delivery could not be confirmed.")
            return delivered

        if action == "verify_funding" and not work["grant_channel_access"]:
            delivered = await ui.send_portal_funding_verified_notice(
                work["user_id"], registration_approved=work["registration_approved"], reason=work["reason"])
            if delivered:
                _complete(
                    db, command_id, "completed", "sent",
                    "Funding was verified. No new PRO Signals invite was issued.",
                )
            else:
                _complete(db, command_id, "uncertain", "uncertain",
                          "Funding verification was saved; private notification delivery could not be confirmed.")
            return delivered

        previous_access = work["previous_access"]
        if previous_access in _UNSAFE_EXISTING_INVITE_STATES:
            _complete(db, command_id, "uncertain", "uncertain",
                      "An earlier invite is pending or uncertain. Check its Telegram operation before taking another action.")
            return False
        if previous_access in _ACTIVE_ACCESS_STATES:
            delivered = await ui.send_portal_pro_approval_notice(work["user_id"])
            if delivered:
                _complete(db, command_id, "completed", "sent", "Existing PRO access was retained; no duplicate invite was created.")
            else:
                _complete(db, command_id, "uncertain", "uncertain",
                          "Existing access was retained, but private notification delivery could not be confirmed.")
            return delivered

        operation_id = publisher.prepare(
            config.admin, "invite",
            {"user": work["user_id"], "channel": config.signals},
        )
        await publisher.send(config.admin, operation_id)
        operation, _ = publisher.operation(operation_id)
        if operation["status"] != "done":
            status = "uncertain" if operation["status"] in ("uncertain", "sending") else "failed"
            delivery = "uncertain" if status == "uncertain" else "failed"
            _complete(db, command_id, status, delivery,
                      "The existing invite operation did not complete normally. Inspect it before any retry.")
            return False
        invite = db.get(f"invite:{operation_id}", {})
        invite_link = invite.get("invite_link") if isinstance(invite, dict) else None
        if not invite_link:
            _complete(db, command_id, "uncertain", "uncertain",
                      "The invite operation completed without a readable invite link. Check the operation before continuing.")
            return False
        delivered = await ui.send_portal_pro_approval_notice(work["user_id"], invite_link)
        if delivered:
            _complete(db, command_id, "completed", "sent", "PRO approval and private invite delivery were recorded.")
        else:
            _complete(db, command_id, "uncertain", "uncertain",
                      "The invite was created, but private delivery could not be confirmed. It will not be resent automatically.")
        return delivered
    except Exception as exc:
        # The step may have reached Telegram despite a timeout. Quarantine it.
        log.warning("portal_pro_review_uncertain:%s", type(exc).__name__)
        try:
            _complete(db, command_id, "uncertain", "uncertain",
                      "A Telegram result could not be confirmed. Check the member chat and existing invite operation before acting again.")
        except Exception:
            log.error("portal_pro_review_result_unrecorded")
        return False


async def run_portal_member_review_worker(db, ui, publisher, config, stop, interval=3):
    if not config.isolated_test or config.database_schema != "smh_test":
        log.warning("portal_pro_review_worker_disabled_outside_isolated_test")
        return
    storage_ready = False
    last_heartbeat = 0.0
    last_error_log = 0.0
    while not stop.is_set():
        try:
            if not storage_ready:
                recover_interrupted_commands(db)
                storage_ready = True
                last_heartbeat = 0.0
            current_time = time.monotonic()
            if current_time - last_heartbeat >= _HEARTBEAT_SECONDS:
                _write_worker_status(db, "ready")
                last_heartbeat = current_time
            pending = db.rows(
                "SELECT id FROM portal_member_review_commands WHERE command_status='queued' "
                "ORDER BY created LIMIT 10"
            )
            for row in pending:
                if stop.is_set():
                    break
                await process_review_command(db, ui, publisher, config, row["id"])
        except Exception as exc:
            # Never log SQL, evidence references, or Telegram URLs.
            storage_ready = False
            try:
                _write_worker_status(db, "unavailable")
            except Exception:
                pass
            if time.monotonic() - last_error_log >= _ERROR_LOG_SECONDS:
                log.warning("portal_pro_review_worker_storage_error:%s", type(exc).__name__)
                last_error_log = time.monotonic()
            try:
                db.error("portal_pro_review_worker", "Review queue storage error; no automatic Telegram retry was made.")
            except Exception:
                pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    try:
        _write_worker_status(db, "stopped")
    except Exception:
        pass
