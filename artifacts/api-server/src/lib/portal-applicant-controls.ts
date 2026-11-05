const destinations = new Set(["education", "analysis", "pro"]);
const resumeBlockedReasons = new Set([
  "awaiting_admin_review",
  "notice_not_seen",
  "uncertain_delivery",
  "maximum_reminders_reached",
  "category_disabled",
]);

export function canManageApplicantControls(
  role: string | undefined,
  nodeEnvironment: string | undefined,
  schema: string,
): boolean {
  return role === "owner" && (
    (nodeEnvironment === "development" && schema === "smh_test") ||
    (nodeEnvironment === "production" && schema === "smh")
  );
}

export function publicMemberAccessApplication(row: Record<string, unknown>) {
  const destination = String(row.destination ?? "");
  if (!destinations.has(destination)) return null;
  return {
    requestId: String(row.id ?? ""),
    userId: String(row.user_id ?? ""),
    username: String(row.username ?? ""),
    destination,
    status: String(row.status ?? ""),
    registrationStatus: String(row.registration_status ?? "not_required"),
    fundingStatus: String(row.funding_status ?? "not_required"),
    source: String(row.source ?? "new"),
    created: String(row.created ?? ""),
    updated: String(row.updated ?? ""),
  };
}

function parseDestinations(value: unknown): string[] {
  let decoded = value;
  if (typeof decoded === "string") {
    try {
      decoded = JSON.parse(decoded) as unknown;
    } catch {
      return [];
    }
  }
  if (!Array.isArray(decoded)) return [];
  return [...new Set(decoded.filter((item): item is string =>
    typeof item === "string" && destinations.has(item)))];
}

export function publicApplicantFollowupState(row: Record<string, unknown>) {
  return {
    userId: String(row.user_id ?? ""),
    username: String(row.username ?? ""),
    privateStatus: String(row.private_status ?? "unknown"),
    stage: String(row.stage ?? ""),
    destinations: parseDestinations(row.destinations),
    status: String(row.status ?? ""),
    pauseReason: String(row.pause_reason ?? ""),
    consentNoticeAt: row.consent_notice_at == null ? null : String(row.consent_notice_at),
    remindersSent: Math.max(0, Number(row.reminders_sent ?? 0) || 0),
    nextFollowup: row.next_followup == null ? null : String(row.next_followup),
    hasRecentError: Boolean(row.last_error),
    updated: String(row.updated ?? ""),
  };
}

export function publicFollowupDelivery(row: Record<string, unknown>) {
  return {
    deliveryId: String(row.id ?? ""),
    category: String(row.category ?? ""),
    status: String(row.status ?? ""),
    created: String(row.created ?? ""),
    updated: String(row.updated ?? ""),
    sentAt: row.sent_at == null ? null : String(row.sent_at),
  };
}

export function publicFollowupEvent(row: Record<string, unknown>) {
  return {
    eventId: String(row.id ?? ""),
    action: String(row.action ?? "").slice(0, 60),
    created: String(row.created ?? ""),
  };
}

export type ApplicantFollowupStatusRow = {
  status: string;
  pause_reason: string;
  private_status: string;
  consent_notice_at: string | null;
  reminders_sent: number;
};

export function followupStatusBlockReason(
  row: ApplicantFollowupStatusRow,
  nextStatus: "active" | "paused",
  maximumReminders: number,
): string | null {
  if (nextStatus === "paused") {
    return row.status === "active" ? null : "Only an active follow-up schedule can be paused.";
  }
  if (row.status !== "paused") return "Only a paused follow-up schedule can be resumed.";
  if (row.private_status !== "available") return "The applicant's private chat is unavailable; this schedule cannot resume.";
  if (!row.consent_notice_at) return "The applicant has not seen the follow-up notice; this schedule cannot resume.";
  if (resumeBlockedReasons.has(row.pause_reason)) {
    return "This schedule is paused for a safety reason that must be resolved in the existing review flow.";
  }
  if (Number(row.reminders_sent) >= maximumReminders) {
    return "The configured reminder limit has been reached.";
  }
  return null;
}

export function safeApplicantFollowupSettings(value: unknown) {
  let decoded = value;
  if (typeof decoded === "string") {
    try {
      decoded = JSON.parse(decoded) as unknown;
    } catch {
      decoded = {};
    }
  }
  const record = decoded && typeof decoded === "object" && !Array.isArray(decoded)
    ? decoded as Record<string, unknown>
    : {};
  const intervals = Array.isArray(record.interval_days)
    ? record.interval_days.filter((day): day is number =>
      Number.isInteger(day) && Number(day) >= 1 && Number(day) <= 90)
    : [2, 5, 9];
  const categories = Array.isArray(record.categories)
    ? record.categories.filter((category): category is string =>
      typeof category === "string" && [
        "application_draft", "information_requested", "registration_step",
        "missing_membership", "welcome",
      ].includes(category))
    : ["application_draft", "information_requested", "registration_step", "missing_membership"];
  return {
    enabled: record.enabled === true,
    reviewed: record.reviewed === true,
    sampleReviewed: record.sample_reviewed === true,
    intervalDays: intervals.length ? intervals : [2, 5, 9],
    maxReminders: Number.isInteger(record.max_reminders) &&
      Number(record.max_reminders) >= 1 && Number(record.max_reminders) <= 10
      ? Number(record.max_reminders) : 3,
    categories: [...new Set(categories)],
  };
}
