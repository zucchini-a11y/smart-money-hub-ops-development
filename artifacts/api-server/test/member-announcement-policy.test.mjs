import test from "node:test";
import assert from "node:assert/strict";
import {
  canEditMemberAnnouncementDraft,
  canManageMemberAnnouncementDrafts,
  canPublishMemberAnnouncement,
  selectDevelopmentAnnouncementRecipients,
} from "../src/lib/member-announcement-policy.ts";

test("only owners and managers can create member announcement drafts", () => {
  assert.equal(canManageMemberAnnouncementDrafts("owner"), true);
  assert.equal(canManageMemberAnnouncementDrafts("manager"), true);
  assert.equal(canManageMemberAnnouncementDrafts("agent"), false);
});

test("managers can edit only their own unpublished drafts", () => {
  assert.equal(canEditMemberAnnouncementDraft("manager", "manager-1", "manager-1", "draft"), true);
  assert.equal(canEditMemberAnnouncementDraft("manager", "manager-1", "manager-2", "draft"), false);
  assert.equal(canEditMemberAnnouncementDraft("manager", "manager-1", "manager-1", "published"), false);
  assert.equal(canEditMemberAnnouncementDraft("owner", "owner-1", "manager-2", "draft"), true);
  assert.equal(canEditMemberAnnouncementDraft("agent", "agent-1", "agent-1", "draft"), false);
});

test("only an owner can publish a draft", () => {
  assert.equal(canPublishMemberAnnouncement("owner", "draft"), true);
  assert.equal(canPublishMemberAnnouncement("manager", "draft"), false);
  assert.equal(canPublishMemberAnnouncement("agent", "draft"), false);
  assert.equal(canPublishMemberAnnouncement("owner", "published"), false);
});

test("audience selection requires a verified non-staff address and removes duplicates", () => {
  const recipients = selectDevelopmentAnnouncementRecipients([
    {
      id: "member-1",
      banned: false,
      primaryEmailAddressId: "email-1",
      emailAddresses: [{ id: "email-1", emailAddress: "Member@Example.com", verification: { status: "verified" } }],
    },
    {
      id: "staff-1",
      banned: false,
      primaryEmailAddressId: "email-2",
      emailAddresses: [{ id: "email-2", emailAddress: "OWNER@example.com", verification: { status: "verified" } }],
    },
    {
      id: "unverified-1",
      banned: false,
      primaryEmailAddressId: "email-3",
      emailAddresses: [{ id: "email-3", emailAddress: "pending@example.com", verification: { status: "unverified" } }],
    },
    {
      id: "banned-1",
      banned: true,
      primaryEmailAddressId: "email-4",
      emailAddresses: [{ id: "email-4", emailAddress: "banned@example.com", verification: { status: "verified" } }],
    },
    {
      id: "member-1",
      banned: false,
      primaryEmailAddressId: "email-5",
      emailAddresses: [{ id: "email-5", emailAddress: "member@example.com", verification: { status: "verified" } }],
    },
  ], [" owner@example.com "]);

  assert.deepEqual(recipients, ["member-1"]);
});
