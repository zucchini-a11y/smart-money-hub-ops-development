import type { PortalRole } from "./portal-case-policy";

export const DEVELOPMENT_ANNOUNCEMENT_AUDIENCE =
  "verified_development_members_excluding_staff" as const;
export const MAX_DEVELOPMENT_CLERK_USERS = 2_000;

export type AnnouncementStatus = "draft" | "published";

export type AnnouncementUserCandidate = {
  id: string;
  banned: boolean;
  primaryEmailAddressId: string | null;
  emailAddresses: Array<{
    id: string;
    emailAddress: string;
    verification?: { status?: string | null } | null;
  }>;
};

export function canManageMemberAnnouncementDrafts(role: PortalRole): boolean {
  return role === "owner" || role === "manager";
}

export function canEditMemberAnnouncementDraft(
  role: PortalRole,
  actorStaffId: string,
  createdByStaffId: string,
  status: AnnouncementStatus,
): boolean {
  if (status !== "draft") return false;
  return role === "owner" || (role === "manager" && actorStaffId === createdByStaffId);
}

export function canPublishMemberAnnouncement(
  role: PortalRole,
  status: AnnouncementStatus,
): boolean {
  return role === "owner" && status === "draft";
}

function verifiedEmail(user: AnnouncementUserCandidate): string | null {
  const primary = user.emailAddresses.find(
    (email) => email.id === user.primaryEmailAddressId && email.verification?.status === "verified",
  );
  const fallback = user.emailAddresses.find(
    (email) => email.verification?.status === "verified",
  );
  const address = primary ?? fallback;
  return address?.emailAddress.trim().toLowerCase() || null;
}

export function selectDevelopmentAnnouncementRecipients(
  users: AnnouncementUserCandidate[],
  staffEmails: Iterable<string>,
): string[] {
  const excludedEmails = new Set(
    [...staffEmails].map((email) => email.trim().toLowerCase()).filter(Boolean),
  );
  const recipientIds = new Set<string>();

  for (const user of users) {
    if (user.banned) continue;
    const email = verifiedEmail(user);
    if (!email || excludedEmails.has(email)) continue;
    recipientIds.add(user.id);
  }

  return [...recipientIds];
}
