import { randomUUID } from "node:crypto";
import { Router, type IRouter, type Request, type Response, type NextFunction } from "express";
import { pool } from "@workspace/db";
import {
  GetPortalApplicantFollowupParams,
  GetPortalApplicantFollowupResponse,
  ListPortalApplicantFollowupsResponse,
  ListPortalMemberApplicationsQueryParams,
  ListPortalMemberApplicationsResponse,
  UpdatePortalApplicantFollowupStatusBody,
  UpdatePortalApplicantFollowupStatusParams,
  UpdatePortalApplicantFollowupStatusResponse,
} from "@workspace/api-zod";
import {
  canManageApplicantControls,
  followupStatusBlockReason,
  publicApplicantFollowupState,
  publicFollowupDelivery,
  publicFollowupEvent,
  publicMemberAccessApplication,
  safeApplicantFollowupSettings,
} from "../lib/portal-applicant-controls";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";
import {
  requirePasswordReady,
  requirePortalSession,
  requireSameOrigin,
} from "../lib/portal-auth";

const router: IRouter = Router();
const supportSchema = resolvePortalSupportSchema(
  process.env.NODE_ENV,
  process.env.PORTAL_SUPPORT_SCHEMA,
);
const safeUserId = /^[0-9]{1,20}$/;

function noStore(_req: Request, res: Response, next: NextFunction): void {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  next();
}

function denyApplicantControlAccess(req: Request, res: Response): boolean {
  if (req.portalIdentity?.role !== "owner") {
    res.status(403).json({ error: "Owner access is required for member and follow-up controls." });
    return true;
  }
  if (!canManageApplicantControls(
    req.portalIdentity.role,
    process.env.NODE_ENV,
    supportSchema,
  )) {
    res.status(404).json({ error: "These controls are available only in the isolated Development environment." });
    return true;
  }
  return false;
}

async function ensureFollowupSchema(res: Response): Promise<boolean> {
  try {
    const result = await pool.query(
      `SELECT version FROM ${supportSchema}.schema_version LIMIT 1`,
    );
    if (Number(result.rows[0]?.version ?? 0) < 9) {
      res.status(503).json({ error: "Apply the applicant follow-up schema migration to the isolated Development database first." });
      return false;
    }
    return true;
  } catch {
    res.status(503).json({ error: "Applicant follow-up data is not available in this Development database yet." });
    return false;
  }
}

function parseSettings(value: unknown) {
  return safeApplicantFollowupSettings(value);
}

router.use(requirePortalSession, requirePasswordReady, noStore);

router.get("/member-applications", async (req, res) => {
  if (denyApplicantControlAccess(req, res)) return;
  const parsed = ListPortalMemberApplicationsQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid member access filter." });
    return;
  }
  try {
    const { destination, status, limit } = parsed.data;
    const result = await pool.query(
      `SELECT id, user_id, username, destination, status, registration_status,
              funding_status, source, created, updated
         FROM ${supportSchema}.member_requests
        WHERE ($1::text IS NULL OR destination = $1)
          AND ($2::text IS NULL OR status = $2)
        ORDER BY updated DESC, created DESC
        LIMIT $3`,
      [destination ?? null, status ?? null, limit ?? 50],
    );
    const body = ListPortalMemberApplicationsResponse.parse({
      scope: process.env.NODE_ENV === "production" ? "production" : "development_test",
      applications: result.rows
        .map((row) => publicMemberAccessApplication(row as Record<string, unknown>))
        .filter((row): row is NonNullable<typeof row> => row !== null),
    });
    res.json(body);
  } catch (error) {
    req.log.error({ err: error }, "Member access overview could not be loaded");
    res.status(503).json({ error: "Member access data is not available in this Development database." });
  }
});

router.get("/applicant-followups", async (req, res) => {
  if (denyApplicantControlAccess(req, res)) return;
  if (!await ensureFollowupSchema(res)) return;
  try {
    const [settingsResult, stateResult] = await Promise.all([
      pool.query(`SELECT value FROM ${supportSchema}.kv WHERE key = $1 LIMIT 1`, [
        "applicant_followup_settings",
      ]),
      pool.query(
        `SELECT state.user_id, state.private_status, state.stage, state.destinations,
                state.status, state.pause_reason, state.consent_notice_at,
                state.reminders_sent, state.next_followup, state.last_error, state.updated,
                COALESCE(latest.username, '') AS username
           FROM ${supportSchema}.applicant_followup_state AS state
           LEFT JOIN LATERAL (
             SELECT username FROM ${supportSchema}.member_requests
              WHERE user_id = state.user_id
              ORDER BY updated DESC LIMIT 1
           ) AS latest ON TRUE
          ORDER BY state.updated DESC
          LIMIT 100`,
      ),
    ]);
    const body = ListPortalApplicantFollowupsResponse.parse({
      scope: process.env.NODE_ENV === "production" ? "production" : "development_test",
      settings: parseSettings(settingsResult.rows[0]?.value),
      applicants: stateResult.rows.map((row) =>
        publicApplicantFollowupState(row as Record<string, unknown>)),
    });
    res.json(body);
  } catch (error) {
    req.log.error({ err: error }, "Applicant follow-up overview could not be loaded");
    res.status(503).json({ error: "Applicant follow-up data is not available in this Development database." });
  }
});

router.get("/applicant-followups/:userId", async (req, res) => {
  if (denyApplicantControlAccess(req, res)) return;
  const params = GetPortalApplicantFollowupParams.safeParse(req.params);
  if (!params.success || !safeUserId.test(params.data.userId)) {
    res.status(400).json({ error: "Invalid applicant identifier." });
    return;
  }
  if (!await ensureFollowupSchema(res)) return;
  try {
    const userId = params.data.userId;
    const [stateResult, deliveriesResult, eventsResult] = await Promise.all([
      pool.query(
        `SELECT state.user_id, state.private_status, state.stage, state.destinations,
                state.status, state.pause_reason, state.consent_notice_at,
                state.reminders_sent, state.next_followup, state.last_error, state.updated,
                COALESCE(latest.username, '') AS username
           FROM ${supportSchema}.applicant_followup_state AS state
           LEFT JOIN LATERAL (
             SELECT username FROM ${supportSchema}.member_requests
              WHERE user_id = state.user_id
              ORDER BY updated DESC LIMIT 1
           ) AS latest ON TRUE
          WHERE state.user_id = $1`,
        [userId],
      ),
      pool.query(
        `SELECT id, category, status, created, updated, sent_at
           FROM ${supportSchema}.applicant_followup_deliveries
          WHERE user_id = $1
          ORDER BY created DESC LIMIT 100`,
        [userId],
      ),
      pool.query(
        `SELECT id, action, created
           FROM ${supportSchema}.applicant_followup_events
          WHERE user_id = $1
          ORDER BY created DESC LIMIT 100`,
        [userId],
      ),
    ]);
    const row = stateResult.rows[0];
    if (!row) {
      res.status(404).json({ error: "Applicant follow-up record was not found." });
      return;
    }
    const body = GetPortalApplicantFollowupResponse.parse({
      applicant: publicApplicantFollowupState(row as Record<string, unknown>),
      deliveries: deliveriesResult.rows.map((item) =>
        publicFollowupDelivery(item as Record<string, unknown>)),
      events: eventsResult.rows.map((item) =>
        publicFollowupEvent(item as Record<string, unknown>)),
    });
    res.json(body);
  } catch (error) {
    req.log.error({ err: error }, "Applicant follow-up detail could not be loaded");
    res.status(503).json({ error: "Applicant follow-up history is not available in this Development database." });
  }
});

router.patch(
  "/applicant-followups/:userId/status",
  requireSameOrigin,
  async (req, res) => {
    if (denyApplicantControlAccess(req, res)) return;
    const params = UpdatePortalApplicantFollowupStatusParams.safeParse(req.params);
    const bodyInput = UpdatePortalApplicantFollowupStatusBody.safeParse(req.body);
    if (!params.success || !safeUserId.test(params.data.userId) || !bodyInput.success) {
      res.status(400).json({ error: "Invalid follow-up status update." });
      return;
    }
    if (!await ensureFollowupSchema(res)) return;

    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const rowResult = await client.query(
        `SELECT user_id, private_status, status, pause_reason, consent_notice_at,
                reminders_sent, updated
           FROM ${supportSchema}.applicant_followup_state
          WHERE user_id = $1
          FOR UPDATE`,
        [params.data.userId],
      );
      const row = rowResult.rows[0];
      if (!row) {
        await client.query("ROLLBACK");
        res.status(404).json({ error: "Applicant follow-up record was not found." });
        return;
      }
      if (String(row.updated) !== bodyInput.data.expectedUpdated) {
        await client.query("ROLLBACK");
        res.status(409).json({ error: "This follow-up record changed. Refresh it before making another change." });
        return;
      }

      const settingsResult = await client.query(
        `SELECT value FROM ${supportSchema}.kv WHERE key = $1 LIMIT 1`,
        ["applicant_followup_settings"],
      );
      const settings = parseSettings(settingsResult.rows[0]?.value);
      const blockReason = followupStatusBlockReason({
        status: String(row.status),
        pause_reason: String(row.pause_reason ?? ""),
        private_status: String(row.private_status ?? "unknown"),
        consent_notice_at: row.consent_notice_at == null ? null : String(row.consent_notice_at),
        reminders_sent: Number(row.reminders_sent ?? 0),
      }, bodyInput.data.status, settings.maxReminders);
      if (blockReason) {
        await client.query("ROLLBACK");
        res.status(409).json({ error: blockReason });
        return;
      }

      const stamp = new Date().toISOString();
      const nextFollowup = bodyInput.data.status === "paused"
        ? null
        : new Date(Date.now() + settings.intervalDays[0] * 24 * 60 * 60 * 1000).toISOString();
      const pauseReason = bodyInput.data.status === "paused" ? "administrator_paused" : "";
      await client.query(
        `UPDATE ${supportSchema}.applicant_followup_state
            SET status = $1, pause_reason = $2, next_followup = $3, updated = $4
          WHERE user_id = $5`,
        [bodyInput.data.status, pauseReason, nextFollowup, stamp, params.data.userId],
      );
      await client.query(
        `INSERT INTO ${supportSchema}.applicant_followup_events
           (id, user_id, delivery_id, action, detail, created)
         VALUES ($1, $2, NULL, $3, $4, $5)`,
        [
          randomUUID(),
          params.data.userId,
          bodyInput.data.status === "paused" ? "portal_followup_paused" : "portal_followup_resumed",
          `Portal owner ${req.portalIdentity?.id ?? "unknown"} set follow-up status to ${bodyInput.data.status}.`,
          stamp,
        ],
      );
      const updatedResult = await client.query(
        `SELECT state.user_id, state.private_status, state.stage, state.destinations,
                state.status, state.pause_reason, state.consent_notice_at,
                state.reminders_sent, state.next_followup, state.last_error, state.updated,
                COALESCE(latest.username, '') AS username
           FROM ${supportSchema}.applicant_followup_state AS state
           LEFT JOIN LATERAL (
             SELECT username FROM ${supportSchema}.member_requests
              WHERE user_id = state.user_id
              ORDER BY updated DESC LIMIT 1
           ) AS latest ON TRUE
          WHERE state.user_id = $1`,
        [params.data.userId],
      );
      await client.query("COMMIT");
      const response = UpdatePortalApplicantFollowupStatusResponse.parse(
        publicApplicantFollowupState(updatedResult.rows[0] as Record<string, unknown>),
      );
      res.json(response);
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      req.log.error({ err: error }, "Applicant follow-up status update failed");
      res.status(503).json({ error: "The follow-up status could not be updated in this Development database." });
    } finally {
      client.release();
    }
  },
);

export default router;
