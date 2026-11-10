import { randomUUID } from "node:crypto";
import { Router, type IRouter, type NextFunction, type Request, type Response } from "express";
import { clerkClient } from "@clerk/express";
import {
  CreatePortalMemberAnnouncementBody,
  CreatePortalMemberAnnouncementResponse,
  ListPortalMemberAnnouncementsResponse,
  PublishPortalMemberAnnouncementBody,
  PublishPortalMemberAnnouncementParams,
  PublishPortalMemberAnnouncementResponse,
  UpdatePortalMemberAnnouncementBody,
  UpdatePortalMemberAnnouncementParams,
  UpdatePortalMemberAnnouncementResponse,
} from "@workspace/api-zod";
import { pool } from "@workspace/db";
import {
  canEditMemberAnnouncementDraft,
  canManageMemberAnnouncementDrafts,
  canPublishMemberAnnouncement,
  DEVELOPMENT_ANNOUNCEMENT_AUDIENCE,
  MAX_DEVELOPMENT_CLERK_USERS,
  selectDevelopmentAnnouncementRecipients,
  type AnnouncementUserCandidate,
} from "../lib/member-announcement-policy";
import {
  requirePasswordReady,
  requirePortalSession,
  requireSameOrigin,
  type PortalIdentity,
} from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";

const router: IRouter = Router();
const schema = resolvePortalSupportSchema(
  process.env.NODE_ENV,
  process.env.PORTAL_SUPPORT_SCHEMA,
);
const pageSize = 100;

function noStore(_req: Request, res: Response, next: NextFunction): void {
  res.setHeader("Cache-Control", "no-store, private");
  res.setHeader("Pragma", "no-cache");
  res.setHeader("X-Content-Type-Options", "nosniff");
  next();
}

function developmentAnnouncementsEnabled(res: Response): boolean {
  if (process.env.NODE_ENV === "production" || schema !== "smh_test") {
    res.status(404).json({ error: "Member announcements are not enabled in this environment." });
    return false;
  }
  return true;
}

function requireDraftRole(req: Request, res: Response): PortalIdentity | null {
  const identity = req.portalIdentity;
  if (!identity || !canManageMemberAnnouncementDrafts(identity.role)) {
    res.status(403).json({ error: "Owner or manager access is required for member announcement drafts." });
    return null;
  }
  return identity;
}

function announcementRowQuery(where = ""): string {
  return `SELECT announcement.announcement_id, announcement.title, announcement.message,
                 announcement.target_path, announcement.status,
                 creator.display_name AS created_by_name, announcement.created_at,
                 publisher.display_name AS published_by_name, announcement.published_at,
                 announcement.recipient_count, announcement.created_by_staff_id
            FROM ${schema}.member_announcements AS announcement
            JOIN ${schema}.portal_users AS creator
              ON creator.id=announcement.created_by_staff_id
            LEFT JOIN ${schema}.portal_users AS publisher
              ON publisher.id=announcement.published_by_staff_id
            ${where}`;
}

function publicAnnouncement(row: Record<string, unknown>) {
  return {
    announcementId: String(row.announcement_id),
    title: String(row.title),
    message: String(row.message),
    targetPath: row.target_path,
    status: row.status,
    createdByName: String(row.created_by_name),
    createdAt: row.created_at,
    publishedByName: row.published_by_name == null ? null : String(row.published_by_name),
    publishedAt: row.published_at ?? null,
    recipientCount: row.recipient_count == null ? null : Number(row.recipient_count),
  };
}

async function addAudit(
  client: { query: (text: string, values?: unknown[]) => Promise<unknown> },
  identity: PortalIdentity,
  action: string,
  announcementId: string,
  detail: string,
): Promise<void> {
  await client.query(
    `INSERT INTO ${schema}.portal_audit
       (id, actor_id, action, entity_id, created, detail)
     VALUES ($1, $2, $3, $4, $5, $6)`,
    [randomUUID().replaceAll("-", ""), identity.id, action, announcementId, new Date().toISOString(), detail],
  );
}

async function listVerifiedDevelopmentMembers(): Promise<string[]> {
  const staffResult = await pool.query(
    `SELECT email FROM ${schema}.portal_users`,
  );
  const staffEmails = staffResult.rows.map((row) => String(row.email));
  const users: AnnouncementUserCandidate[] = [];
  let offset = 0;
  let totalCount: number | null = null;

  while (true) {
    const page = await clerkClient.users.getUserList({
      limit: pageSize,
      offset,
      orderBy: "-created_at",
    });
    totalCount ??= page.totalCount;
    if (totalCount > MAX_DEVELOPMENT_CLERK_USERS) {
      throw new Error("Development Clerk audience exceeds the synchronous publish limit.");
    }
    users.push(...page.data.map((user) => ({
      id: user.id,
      banned: user.banned,
      primaryEmailAddressId: user.primaryEmailAddressId,
      emailAddresses: (user.emailAddresses ?? []).map((email) => ({
        id: email.id,
        emailAddress: email.emailAddress,
        verification: email.verification ? { status: email.verification.status } : null,
      })),
    })));
    offset += page.data.length;
    if (page.data.length < pageSize || offset >= totalCount) break;
  }

  return selectDevelopmentAnnouncementRecipients(users, staffEmails);
}

router.use(
  "/portal/member-announcements",
  noStore,
  requirePortalSession,
  requirePasswordReady,
);

router.get("/portal/member-announcements", async (req, res): Promise<void> => {
  if (!developmentAnnouncementsEnabled(res)) return;
  const identity = requireDraftRole(req, res);
  if (!identity) return;

  const where = identity.role === "owner"
    ? ""
    : "WHERE announcement.created_by_staff_id=$1";
  const values = identity.role === "owner" ? [] : [identity.id];
  const result = await pool.query(
    `${announcementRowQuery(where)}
      ORDER BY announcement.created_at DESC
      LIMIT 100`,
    values,
  );
  res.json(ListPortalMemberAnnouncementsResponse.parse({
    announcements: result.rows.map(publicAnnouncement),
    role: identity.role,
    audienceLabel: DEVELOPMENT_ANNOUNCEMENT_AUDIENCE,
  }));
});

router.post(
  "/portal/member-announcements",
  requireSameOrigin,
  async (req, res): Promise<void> => {
    if (!developmentAnnouncementsEnabled(res)) return;
    const identity = requireDraftRole(req, res);
    if (!identity) return;

    const parsed = CreatePortalMemberAnnouncementBody.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: "Enter a title, message, and member destination." });
      return;
    }
    const data = {
      title: parsed.data.title.trim(),
      message: parsed.data.message.trim(),
      targetPath: parsed.data.targetPath,
      requestId: parsed.data.requestId,
    };
    if (!data.title || !data.message) {
      res.status(400).json({ error: "Title and message cannot be blank." });
      return;
    }

    const announcementId = randomUUID();
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const inserted = await client.query(
        `INSERT INTO ${schema}.member_announcements
          (announcement_id, created_by_staff_id, request_id, title, message, target_path)
         VALUES ($1, $2, $3, $4, $5, $6)
         ON CONFLICT (created_by_staff_id, request_id) DO NOTHING
         RETURNING announcement_id`,
        [announcementId, identity.id, data.requestId, data.title, data.message, data.targetPath],
      );
      const createdId = inserted.rows[0]?.announcement_id;
      if (!createdId) {
        const existing = await client.query(
          `${announcementRowQuery("WHERE announcement.created_by_staff_id=$1 AND announcement.request_id=$2")}
           LIMIT 1`,
          [identity.id, data.requestId],
        );
        if (!existing.rows[0]) throw new Error("Idempotent announcement draft could not be loaded.");
        await client.query("COMMIT");
        res.status(200).json(CreatePortalMemberAnnouncementResponse.parse({
          announcement: publicAnnouncement(existing.rows[0]),
        }));
        return;
      }
      await addAudit(
        client,
        identity,
        "member_announcement_draft_created",
        String(createdId),
        "Created a Development member announcement draft.",
      );
      const result = await client.query(
        `${announcementRowQuery("WHERE announcement.announcement_id=$1")} LIMIT 1`,
        [createdId],
      );
      await client.query("COMMIT");
      res.status(201).json(CreatePortalMemberAnnouncementResponse.parse({
        announcement: publicAnnouncement(result.rows[0]),
      }));
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  },
);

router.patch(
  "/portal/member-announcements/:announcementId",
  requireSameOrigin,
  async (req, res): Promise<void> => {
    if (!developmentAnnouncementsEnabled(res)) return;
    const identity = requireDraftRole(req, res);
    if (!identity) return;

    const params = UpdatePortalMemberAnnouncementParams.safeParse(req.params);
    const parsed = UpdatePortalMemberAnnouncementBody.safeParse(req.body);
    if (!params.success || !parsed.success) {
      res.status(400).json({ error: "Enter a valid draft identifier, title, message, and destination." });
      return;
    }
    const title = parsed.data.title.trim();
    const message = parsed.data.message.trim();
    if (!title || !message) {
      res.status(400).json({ error: "Title and message cannot be blank." });
      return;
    }

    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const current = await client.query(
        `SELECT announcement_id, created_by_staff_id, status
           FROM ${schema}.member_announcements
          WHERE announcement_id=$1
          FOR UPDATE`,
        [params.data.announcementId],
      );
      const row = current.rows[0];
      if (!row) {
        await client.query("ROLLBACK");
        res.status(404).json({ error: "Draft not found or not editable." });
        return;
      }
      if (!canEditMemberAnnouncementDraft(
        identity.role,
        identity.id,
        String(row.created_by_staff_id),
        row.status,
      )) {
        await client.query("ROLLBACK");
        res.status(row.status === "published" ? 409 : 404).json({
          error: row.status === "published"
            ? "Published announcements cannot be edited."
            : "Draft not found or not editable.",
        });
        return;
      }
      await client.query(
        `UPDATE ${schema}.member_announcements
            SET title=$1, message=$2, target_path=$3, updated_at=NOW()
          WHERE announcement_id=$4`,
        [title, message, parsed.data.targetPath, params.data.announcementId],
      );
      await addAudit(
        client,
        identity,
        "member_announcement_draft_updated",
        params.data.announcementId,
        "Updated a Development member announcement draft.",
      );
      const result = await client.query(
        `${announcementRowQuery("WHERE announcement.announcement_id=$1")} LIMIT 1`,
        [params.data.announcementId],
      );
      await client.query("COMMIT");
      res.json(UpdatePortalMemberAnnouncementResponse.parse({
        announcement: publicAnnouncement(result.rows[0]),
      }));
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  },
);

router.post(
  "/portal/member-announcements/:announcementId/publish",
  requireSameOrigin,
  async (req, res): Promise<void> => {
    if (!developmentAnnouncementsEnabled(res)) return;
    const identity = req.portalIdentity;
    if (!identity || !canPublishMemberAnnouncement(identity.role, "draft")) {
      res.status(403).json({ error: "Only an Owner can publish member announcements." });
      return;
    }
    const params = PublishPortalMemberAnnouncementParams.safeParse(req.params);
    const parsed = PublishPortalMemberAnnouncementBody.safeParse(req.body);
    if (!params.success || !parsed.success) {
      res.status(400).json({ error: "Confirm the publication and provide a valid draft identifier." });
      return;
    }

    let recipientIds: string[];
    try {
      recipientIds = await listVerifiedDevelopmentMembers();
    } catch (error) {
      req.log.error(
        { errorType: error instanceof Error ? error.name : "UnknownError" },
        "Development announcement audience lookup failed",
      );
      res.status(503).json({
        error: "The Development member audience could not be verified. Nothing was published.",
      });
      return;
    }
    if (recipientIds.length === 0) {
      res.status(409).json({
        error: "No verified, non-staff Development members are available. The draft was not published.",
      });
      return;
    }

    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const current = await client.query(
        `SELECT announcement_id, status, title, message, target_path, recipient_count
           FROM ${schema}.member_announcements
          WHERE announcement_id=$1
          FOR UPDATE`,
        [params.data.announcementId],
      );
      const row = current.rows[0];
      if (!row) {
        await client.query("ROLLBACK");
        res.status(404).json({ error: "Announcement draft not found." });
        return;
      }
      if (row.status === "published") {
        const published = await client.query(
          `${announcementRowQuery("WHERE announcement.announcement_id=$1")} LIMIT 1`,
          [params.data.announcementId],
        );
        await client.query("ROLLBACK");
        res.json(PublishPortalMemberAnnouncementResponse.parse({
          announcement: publicAnnouncement(published.rows[0]),
          recipientCount: Number(row.recipient_count ?? 0),
          audienceLabel: DEVELOPMENT_ANNOUNCEMENT_AUDIENCE,
        }));
        return;
      }
      if (row.status !== "draft") {
        await client.query("ROLLBACK");
        res.status(409).json({ error: "This announcement is not available to publish." });
        return;
      }

      const insertedIds = recipientIds.map(() => randomUUID());
      const inserted = await client.query(
        `INSERT INTO ${schema}.member_notifications
          (notification_id, clerk_user_id, idempotency_key, kind, title, message, target_path)
         SELECT targets.notification_id,
                targets.clerk_user_id,
                'announcement:' || $3,
                'announcement',
                $4,
                $5,
                $6
           FROM unnest($1::uuid[], $2::text[]) AS targets(notification_id, clerk_user_id)
         ON CONFLICT (clerk_user_id, idempotency_key) DO NOTHING`,
        [
          insertedIds,
          recipientIds,
          params.data.announcementId,
          String(row.title),
          String(row.message),
          String(row.target_path),
        ],
      );
      const recipientCount = inserted.rowCount ?? 0;
      if (recipientCount === 0) {
        await client.query("ROLLBACK");
        res.status(409).json({
          error: "No new member notifications were created. The draft remains unpublished.",
        });
        return;
      }

      await client.query(
        `UPDATE ${schema}.member_announcements
            SET status='published',
                published_by_staff_id=$1,
                published_at=NOW(),
                recipient_count=$2,
                updated_at=NOW()
          WHERE announcement_id=$3`,
        [identity.id, recipientCount, params.data.announcementId],
      );
      await addAudit(
        client,
        identity,
        "member_announcement_published",
        params.data.announcementId,
        `Created ${recipientCount} Development in-app member notifications.`,
      );
      const published = await client.query(
        `${announcementRowQuery("WHERE announcement.announcement_id=$1")} LIMIT 1`,
        [params.data.announcementId],
      );
      await client.query("COMMIT");
      res.json(PublishPortalMemberAnnouncementResponse.parse({
        announcement: publicAnnouncement(published.rows[0]),
        recipientCount,
        audienceLabel: DEVELOPMENT_ANNOUNCEMENT_AUDIENCE,
      }));
    } catch (error) {
      await client.query("ROLLBACK");
      throw error;
    } finally {
      client.release();
    }
  },
);

export default router;
