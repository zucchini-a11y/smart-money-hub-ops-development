import test from "node:test";
import assert from "node:assert/strict";
import {
  canManageApplicantControls,
  followupStatusBlockReason,
  publicApplicantFollowupState,
  publicFollowupDelivery,
  publicFollowupEvent,
  publicMemberAccessApplication,
  safeApplicantFollowupSettings,
} from "../src/lib/portal-applicant-controls.ts";

test("member and follow-up portal access is restricted to the owner and active deployment schema", () => {
  assert.equal(canManageApplicantControls("owner", "development", "smh_test"), true);
  assert.equal(canManageApplicantControls("manager", "development", "smh_test"), false);
  assert.equal(canManageApplicantControls("agent", "development", "smh_test"), false);
  assert.equal(canManageApplicantControls("owner", "production", "smh"), true);
  assert.equal(canManageApplicantControls("owner", "production", "smh_test"), false);
  assert.equal(canManageApplicantControls("owner", "development", "smh"), false);
});

test("member access projection excludes answers, private replies, and evidence identifiers", () => {
  const row = publicMemberAccessApplication({
    id: "request-1", user_id: 1234, username: "member", destination: "analysis",
    status: "pending_review", registration_status: "not_required",
    funding_status: "not_required", source: "new",
    answers: "private answers", followup_text: "private reply",
    evidence_file_id: "telegram-file-id", created: "2026-10-20", updated: "2026-10-21",
  });
  assert.equal(row.destination, "analysis");
  assert.equal("answers" in row, false);
  assert.equal("followup_text" in row, false);
  assert.equal("evidence_file_id" in row, false);
  assert.equal(JSON.stringify(row).includes("telegram-file-id"), false);
  assert.equal(publicMemberAccessApplication({ destination: "unknown" }), null);
});

test("follow-up status changes block opt-out, missing consent, uncertain sends, and exhausted schedules", () => {
  const base = {
    status: "paused", pause_reason: "administrator_paused",
    private_status: "available", consent_notice_at: "2026-10-20T00:00:00Z",
    reminders_sent: 1,
  };
  assert.equal(followupStatusBlockReason(base, "active", 3), null);
  assert.match(followupStatusBlockReason({ ...base, pause_reason: "uncertain_delivery" }, "active", 3), /safety reason/);
  assert.match(followupStatusBlockReason({ ...base, consent_notice_at: null }, "active", 3), /has not seen/);
  assert.match(followupStatusBlockReason({ ...base, private_status: "blocked" }, "active", 3), /private chat/);
  assert.match(followupStatusBlockReason({ ...base, status: "opted_out" }, "active", 3), /paused/);
  assert.match(followupStatusBlockReason({ ...base, reminders_sent: 3 }, "active", 3), /limit/);
  assert.equal(followupStatusBlockReason({ ...base, status: "active" }, "paused", 3), null);
});

test("follow-up projections return status only and never expose message or event details", () => {
  const state = publicApplicantFollowupState({
    user_id: 1234, username: "member", private_status: "available", stage: "welcome",
    destinations: '["education","fake"]', status: "paused", pause_reason: "administrator_paused",
    consent_notice_at: null, reminders_sent: 0, next_followup: null,
    last_error: "Forbidden", updated: "2026-10-21",
    message: "private message", evidence_file_id: "secret-file",
  });
  assert.deepEqual(state.destinations, ["education"]);
  assert.equal(state.hasRecentError, true);
  assert.equal("message" in state, false);
  assert.equal(JSON.stringify(state).includes("secret-file"), false);

  const delivery = publicFollowupDelivery({
    id: "delivery-1", category: "welcome", status: "sent",
    message: "private content", created: "2026-10-20", updated: "2026-10-20",
    sent_at: "2026-10-20", error_category: "private error detail",
  });
  const event = publicFollowupEvent({
    id: "event-1", action: "delivery_sent", detail: "private detail",
    created: "2026-10-20",
  });
  assert.equal("message" in delivery, false);
  assert.equal("detail" in event, false);
  assert.equal(JSON.stringify([delivery, event]).includes("private"), false);
});

test("follow-up settings are bounded and safely normalized", () => {
  assert.deepEqual(safeApplicantFollowupSettings({
    enabled: true, reviewed: true, sample_reviewed: true,
    interval_days: [1, 5, 91, "8"], max_reminders: 11,
    categories: ["welcome", "forged"],
  }), {
    enabled: true, reviewed: true, sampleReviewed: true,
    intervalDays: [1, 5], maxReminders: 3, categories: ["welcome"],
  });
  assert.equal(safeApplicantFollowupSettings("invalid").enabled, false);
});
