import test from "node:test";
import assert from "node:assert/strict";
import {
  canManageProReviews,
  mayQueueProReviewAction,
  publicProApplication,
  safeProReviewEvent,
  downloadTelegramEvidence,
  isProReviewWorkerReady,
} from "../src/lib/pro-member-review-policy.ts";

test("PRO review actions are owner-only and isolated to Development smh_test", () => {
  assert.equal(canManageProReviews("owner", "development", "smh_test"), true);
  assert.equal(canManageProReviews("manager", "development", "smh_test"), false);
  assert.equal(canManageProReviews("agent", "development", "smh_test"), false);
  assert.equal(canManageProReviews("owner", "production", "smh_test"), false);
  assert.equal(canManageProReviews("owner", "development", "smh"), false);
});

test("registration approval grants education eligibility only and never grants channel access", () => {
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "pending_review",
    funding_status: "not_submitted",
  }, "approve_registration"), true);
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "verified",
    funding_status: "not_submitted",
  }, "approve_registration"), false);
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "pending_review",
    funding_status: "not_submitted",
  }, "reject_registration"), true);
});

test("funding verification requires evidence and only final approval requires both gates", () => {
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "approved",
    funding_status: "pending_review",
    has_evidence: true,
  }, "verify_funding"), true);
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "pending_review",
    funding_status: "pending_review",
    has_evidence: false,
  }, "verify_funding"), false);
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "verified",
    funding_status: "verified",
  }, "approve"), true);
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "pending_review",
    funding_status: "verified",
  }, "approve"), false);
  assert.equal(mayQueueProReviewAction({
    status: "approved",
    registration_status: "verified",
    funding_status: "verified",
  }, "approve"), false);
});

test("pending verification cannot be rejected and approved access cannot be rejected as an application", () => {
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "verified",
    funding_status: "pending_review",
  }, "reject"), false);
  assert.equal(mayQueueProReviewAction({
    status: "approved",
    registration_status: "verified",
    funding_status: "verified",
  }, "reject"), false);
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "verified",
    funding_status: "verified",
  }, "reject"), true);
});

test("evidence requests preserve approved access and cannot be duplicated while awaiting evidence", () => {
  assert.equal(mayQueueProReviewAction({
    status: "approved",
    registration_status: "verified",
    funding_status: "verified",
  }, "request_evidence"), true);
  assert.equal(mayQueueProReviewAction({
    status: "approved",
    registration_status: "verified",
    funding_status: "evidence_requested",
  }, "request_evidence"), false);
  assert.equal(mayQueueProReviewAction({
    status: "approved",
    registration_status: "pending_review",
    funding_status: "verified",
  }, "request_evidence"), false);
});

test("funding evidence rejection is separate and requires submitted evidence", () => {
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "approved",
    funding_status: "pending_review",
    has_evidence: true,
  }, "reject_funding"), true);
  assert.equal(mayQueueProReviewAction({
    status: "pending_review",
    registration_status: "approved",
    funding_status: "pending_review",
    has_evidence: false,
  }, "reject_funding"), false);
});

test("public application projection does not expose evidence IDs or raw answers", () => {
  const result = publicProApplication({
    id: "request-1",
    user_id: 12345,
    username: "member",
    status: "pending_review",
    registration_status: "approved",
    funding_status: "pending_review",
    channel_access_status: "not_issued",
    source: "new",
    evidence_file_id: "secret-file-reference",
    evidence_kind: "image/jpeg",
    evidence_submitted_at: "2026-10-19T10:00:00Z",
    answers: "raw private application answers",
    created: "2026-10-18T10:00:00Z",
    updated: "2026-10-19T10:00:00Z",
  });
  assert.equal(result.userId, "12345");
  assert.equal(result.hasEvidence, true);
  assert.equal(result.educationEligibility, "eligible_delivery_disabled");
  assert.equal(result.channelAccessStatus, "not_issued");
  assert.equal("evidenceFileId" in result, false);
  assert.equal("answers" in result, false);
  assert.equal(JSON.stringify(result).includes("secret-file-reference"), false);
});

test("member history projection hides database actor IDs and event details", () => {
  const result = safeProReviewEvent({
    id: 9,
    actor: 12345,
    action: "funding_evidence_submitted",
    detail: "Contains an internal file ID",
    created: "2026-10-19T10:00:00Z",
  }, "12345");
  assert.equal(result.actor, "Applicant");
  assert.equal(result.reason, "");
  assert.equal(JSON.stringify(result).includes("12345"), false);
  assert.equal(JSON.stringify(result).includes("internal file ID"), false);
});

test("evidence download is bounded and uses only the fixed Telegram file host", async () => {
  const urls = [];
  let call = 0;
  const fetcher = async (url) => {
    urls.push(String(url));
    call += 1;
    if (call === 1) {
      return {
        ok: true,
        json: async () => ({ ok: true, result: { file_path: "photos/evidence.jpg", file_size: 4 } }),
      };
    }
    return {
      ok: true,
      headers: { get: () => "4" },
      arrayBuffer: async () => Uint8Array.from([1, 2, 3, 4]).buffer,
    };
  };
  const result = await downloadTelegramEvidence("synthetic-test-token", "synthetic-file-id", "image/jpeg", fetcher);
  assert.deepEqual([...result.body], [1, 2, 3, 4]);
  assert.equal(result.contentType, "image/jpeg");
  assert.equal(urls.length, 2);
  assert.ok(urls.every((url) => url.startsWith("https://api.telegram.org/")));
});

test("evidence download rejects unsafe paths, unsupported types, and oversized files", async () => {
  let calls = 0;
  const fetcher = async () => {
    calls += 1;
    return {
      ok: true,
      json: async () => ({ ok: true, result: { file_path: "../../outside.jpg", file_size: 4 } }),
    };
  };
  assert.equal(await downloadTelegramEvidence("synthetic", "file", "image/jpeg", fetcher), null);
  assert.equal(await downloadTelegramEvidence("synthetic", "file", "text/html", fetcher), null);
  assert.equal(calls, 1);

  const oversized = async () => ({
    ok: true,
    json: async () => ({
      ok: true,
      result: { file_path: "photos/large.jpg", file_size: 10 * 1024 * 1024 + 1 },
    }),
  });
  assert.equal(await downloadTelegramEvidence("synthetic", "file", "image/jpeg", oversized), null);
});

test("review decisions are enabled only while the matching isolated worker heartbeat is fresh", () => {
  const nowMs = Date.parse("2026-10-19T10:00:00.000Z");
  assert.equal(isProReviewWorkerReady({
    version: "pro-review-v1",
    status: "ready",
    updated: "2026-10-19T09:59:30.000Z",
  }, nowMs), true);
  assert.equal(isProReviewWorkerReady(JSON.stringify({
    version: "pro-review-v1",
    status: "ready",
    updated: "2026-10-19T09:57:00.000Z",
  }), nowMs), false);
  assert.equal(isProReviewWorkerReady({
    version: "old-worker",
    status: "ready",
    updated: "2026-10-19T09:59:30.000Z",
  }, nowMs), false);
  assert.equal(isProReviewWorkerReady({
    version: "pro-review-v1",
    status: "unavailable",
    updated: "2026-10-19T09:59:30.000Z",
  }, nowMs), false);
});
