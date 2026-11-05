export type ProReviewAction =
  | "approve_registration"
  | "reject_registration"
  | "verify_funding"
  | "reject_funding"
  | "approve"
  | "reject"
  | "request_evidence";

export type ProApplicationState = {
  status: string;
  registration_status: string;
  funding_status: string;
  has_evidence?: boolean;
};

export function isProReviewWorkerReady(
  value: unknown,
  nowMs = Date.now(),
  maxAgeMs = 90_000,
): boolean {
  let heartbeat = value;
  if (typeof heartbeat === "string") {
    try {
      heartbeat = JSON.parse(heartbeat) as unknown;
    } catch {
      return false;
    }
  }
  if (!heartbeat || typeof heartbeat !== "object" || Array.isArray(heartbeat)) return false;
  const record = heartbeat as Record<string, unknown>;
  if (record.version !== "pro-review-v1" || record.status !== "ready" ||
      typeof record.updated !== "string") return false;
  const updatedMs = Date.parse(record.updated);
  return Number.isFinite(updatedMs) && updatedMs <= nowMs + 30_000 &&
    nowMs - updatedMs <= maxAgeMs;
}

export function canManageProReviews(
  role: string | undefined,
  nodeEnvironment: string | undefined,
  schema: string,
): boolean {
  return role === "owner" && nodeEnvironment === "development" && schema === "smh_test";
}

export function mayQueueProReviewAction(
  application: ProApplicationState,
  action: ProReviewAction,
): boolean {
  const { status, registration_status: registration, funding_status: funding } = application;
  const registrationApproved = registration === "approved" || registration === "verified";
  const reviewable = ["pending_review", "legacy_review", "information_requested"].includes(status);
  if (action === "approve_registration") {
    return ["pending_review", "legacy_review"].includes(status) &&
      ["pending_review", "unverified"].includes(registration);
  }
  if (action === "reject_registration") {
    return ["pending_review", "legacy_review"].includes(status) &&
      ["pending_review", "unverified"].includes(registration);
  }
  if (action === "verify_funding") {
    return ["pending_review", "legacy_review", "information_requested", "approved"].includes(status) &&
      funding === "pending_review" && application.has_evidence === true;
  }
  if (action === "reject_funding") {
    return reviewable && status !== "approved" && funding === "pending_review" &&
      application.has_evidence === true;
  }
  if (action === "approve") {
    return ["pending_review", "legacy_review"].includes(status) &&
      registrationApproved && funding === "verified";
  }
  if (action === "reject") {
    return !["approved", "rejected", "not_yet_eligible", "revoked"].includes(status) &&
      registration !== "pending_review" && funding !== "pending_review";
  }
  if (action === "request_evidence") {
    if (!["pending_review", "legacy_review", "information_requested", "approved"].includes(status) ||
        funding === "pending_review" || funding === "evidence_requested") {
      return false;
    }
    return status !== "approved" || registrationApproved;
  }
  return false;
}

export function publicProApplication(row: Record<string, unknown>) {
  return {
    requestId: String(row.id),
    userId: String(row.user_id),
    username: String(row.username ?? ""),
    status: String(row.status),
    registrationStatus: String(row.registration_status),
    fundingStatus: String(row.funding_status),
    educationEligibility:
      (String(row.registration_status) === "approved" ||
       String(row.registration_status) === "verified") &&
      !["rejected", "revoked"].includes(String(row.status))
        ? "eligible_delivery_disabled"
        : "locked",
    channelAccessStatus: String(row.channel_access_status ?? "not_issued"),
    source: String(row.source ?? "new"),
    hasEvidence: Boolean(row.evidence_file_id),
    evidenceKind: row.evidence_kind == null ? null : String(row.evidence_kind),
    evidenceSubmittedAt: row.evidence_submitted_at == null ? null : String(row.evidence_submitted_at),
    created: String(row.created),
    updated: String(row.updated),
  };
}

export function safeProReviewEvent(row: Record<string, unknown>, applicantUserId: string) {
  const actorId = String(row.actor ?? "");
  return {
    eventId: String(row.event_id ?? row.id),
    action: String(row.action ?? ""),
    actor: actorId === applicantUserId ? "Applicant" : "Bot administrator",
    reason: "",
    status: "recorded",
    deliveryStatus: "not_attempted",
    created: String(row.created ?? ""),
    completedAt: null,
  };
}

export function safeProReviewCommand(row: Record<string, unknown>) {
  return {
    commandId: String(row.id),
    requestId: String(row.request_id),
    action: String(row.action) as ProReviewAction,
    status: String(row.command_status) as
      "queued" | "processing" | "completed" | "failed" | "uncertain" | "stale",
    deliveryStatus: String(row.delivery_status) as
      "not_attempted" | "sent" | "failed" | "uncertain" | "not_needed",
    safeResult: String(row.safe_result ?? ""),
    created: String(row.created),
    updated: String(row.updated),
    completedAt: row.completed_at == null ? null : String(row.completed_at),
  };
}

const ALLOWED_EVIDENCE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "application/pdf",
]);
const MAX_EVIDENCE_BYTES = 10 * 1024 * 1024;

export async function downloadTelegramEvidence(
  token: string,
  fileId: string,
  mimeType: string,
  fetcher: typeof fetch = fetch,
): Promise<{ contentType: string; body: Uint8Array } | null> {
  if (!token || !fileId || !ALLOWED_EVIDENCE_TYPES.has(mimeType)) return null;
  try {
    const fileInfoResponse = await fetcher(
      `https://api.telegram.org/bot${token}/getFile?file_id=${encodeURIComponent(fileId)}`,
      { signal: AbortSignal.timeout(10_000) },
    );
    if (!fileInfoResponse.ok) return null;
    const fileInfo = await fileInfoResponse.json() as {
      ok?: boolean;
      result?: { file_path?: string; file_size?: number };
    };
    const path = fileInfo.result?.file_path;
    if (!fileInfo.ok || !path || path.split("/").some((part) => !part || part === "." || part === "..") ||
        !/^[A-Za-z0-9_./-]+$/.test(path) ||
        (fileInfo.result?.file_size != null && fileInfo.result.file_size > MAX_EVIDENCE_BYTES)) {
      return null;
    }
    const encodedPath = path.split("/").map(encodeURIComponent).join("/");
    const fileResponse = await fetcher(
      `https://api.telegram.org/file/bot${token}/${encodedPath}`,
      { signal: AbortSignal.timeout(15_000) },
    );
    if (!fileResponse.ok) return null;
    const reportedLength = Number(fileResponse.headers.get("content-length") ?? 0);
    if (reportedLength > MAX_EVIDENCE_BYTES) return null;
    const body = new Uint8Array(await fileResponse.arrayBuffer());
    if (body.byteLength === 0 || body.byteLength > MAX_EVIDENCE_BYTES) return null;
    return { contentType: mimeType, body };
  } catch {
    // Keep the token-bearing Telegram URL and provider response out of logs/errors.
    return null;
  }
}
