import { createHash, randomUUID } from "node:crypto";
import { Router, type IRouter, type Request, type Response, type NextFunction } from "express";
import { pool as databasePool } from "@workspace/db";
import {
  ChangePortalPasswordBody,
  ChangePortalPasswordResponse,
  AssignPortalCaseBody,
  AssignPortalCaseParams,
  AssignPortalCaseResponse,
  AddPortalCaseNoteBody,
  AddPortalCaseNoteParams,
  AddPortalCaseNoteResponse,
  UpdateStaffTaskParams,
  UpdateStaffTaskBody,
  UpdateStaffTaskResponse,
  ListStaffActivityReportsResponse,
  SubmitStaffActivityReportBody,
  SubmitStaffActivityReportResponse,
  ReviewStaffActivityReportParams,
  ReviewStaffActivityReportBody,
  ReviewStaffActivityReportResponse,
  GetStaffPerformanceResponse,
  ListStaffReportNotificationsResponse,
  MarkStaffReportNotificationReadParams,
  MarkStaffReportNotificationReadResponse,
  ListStaffTasksResponse,
  CreateStaffTaskBody,
  CreateStaffTaskResponse,
  GetStaffTaskParams,
  GetStaffTaskResponse,
  UpdateStaffTaskStatusParams,
  UpdateStaffTaskStatusBody,
  UpdateStaffTaskStatusResponse,
  ListStaffTeamsResponse,
  CreateStaffTeamBody,
  CreateStaffTeamResponse,
  SetStaffTeamMembersParams,
  SetStaffTeamMembersBody,
  SetStaffTeamMembersResponse,
  ListStaffTaskNotificationsResponse,
  MarkStaffTaskNotificationReadParams,
  MarkStaffTaskNotificationReadResponse,
  ClosePortalCaseParams,
  ClosePortalCaseResponse,
  CreatePortalCaseReplyBody,
  CreatePortalCaseReplyParams,
  CreatePortalCaseReplyResponse,
  CreatePortalStaffBody,
  CreatePortalStaffResponse,
  GetPortalCaseParams,
  GetPortalCaseResponse,
  GetPortalDashboardResponse,
  GetPortalCommandCenterResponse,
  GetPortalChannelHistoryQueryParams,
  GetPortalChannelHistoryResponse,
  ListPortalTradesResponse,
  GetPortalSignalControlResponse,
  CreatePortalSignalActionBody,
  CreatePortalSignalActionResponse,
  GetPortalSignalActionParams,
  GetPortalSignalActionResponse,
  ConfirmPortalSignalActionParams,
  ConfirmPortalSignalActionResponse,
  CancelPortalSignalActionParams,
  CancelPortalSignalActionResponse,
  GetPortalTradeParams,
  GetPortalTradeResponse,
  CreatePortalTradeActionParams,
  CreatePortalTradeActionBody,
  CreatePortalTradeActionResponse,
  GetPortalTradeActionParams,
  GetPortalTradeActionResponse,
  ConfirmPortalTradeActionParams,
  ConfirmPortalTradeActionResponse,
  CancelPortalTradeActionParams,
  CancelPortalTradeActionResponse,
  GetPortalSessionResponse,
  GetProMemberApplicationParams,
  GetProMemberApplicationResponse,
  ListProMemberApplicationsQueryParams,
  ListProMemberApplicationsResponse,
  ListPortalCasesQueryParams,
  ListPortalCasesResponse,
  ListPortalStaffResponse,
  PortalLoginBody,
  PortalLoginResponse,
  PortalLogoutResponse,
  SubmitProMemberReviewDecisionBody,
  SubmitProMemberReviewDecisionParams,
  SubmitProMemberReviewDecisionResponse,
  UpdatePortalStaffBody,
  UpdatePortalStaffParams,
  UpdatePortalStaffResponse,
} from "@workspace/api-zod";
import {
  clearPortalSessionCookie,
  requirePasswordReady,
  requirePortalSession,
  requireSameOrigin,
  setPortalSessionCookie,
  toPortalSession,
  type PortalIdentity,
} from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";
import {
  canViewOwnerCommandCenter,
  isDevelopmentCommandCenterAvailable,
} from "../lib/owner-command-center-policy";
import { readDevelopmentCommandCenter } from "../lib/portal-command-center";
import { readDevelopmentChannelHistory } from "../lib/portal-channel-history";
import {
  canManageProReviews,
  downloadTelegramEvidence,
  isProReviewWorkerReady,
  mayQueueProReviewAction,
  publicProApplication,
  safeProReviewCommand,
  safeProReviewEvent,
} from "../lib/pro-member-review-policy";
import {
  hashPassword,
  hashSessionToken,
  makeSessionToken,
  makeTemporaryPassword,
  verifyPassword,
} from "../lib/portal-crypto";
import { canManageCases, canManageStaff } from "../lib/portal-case-policy";
import { canAccessStaffTask, mayChangeTaskStatus, type StaffTaskStatus } from "../lib/staff-task-policy";
import {
  isTradeManagementAvailable,
  normalizeTradeActionInput,
  publicTradeAction,
  readPortalTrade,
  readPortalTrades,
  workerSnapshot,
  type TradeAction,
  type TradeActionValues,
} from "../lib/portal-trade-management";
import {
  isPortalSignalControlAvailable,
  normalizePortalSignalInput,
  publicSignalCommand,
  readPortalSignalPanel,
  signalWorkerSnapshot,
  type SignalAction,
} from "../lib/portal-signal-control";

const router: IRouter = Router();
const supportSchema = resolvePortalSupportSchema(
  process.env.NODE_ENV,
  process.env.PORTAL_SUPPORT_SCHEMA,
);
function rewritePortalSchemaQuery(query: unknown): unknown {
  const rewrite = (sql: string) => sql.replace(/\bsmh\./g, `${supportSchema}.`);
  if (typeof query === "string") return rewrite(query);
  if (
    query &&
    typeof query === "object" &&
    "text" in query &&
    typeof query.text === "string"
  ) {
    return { ...query, text: rewrite(query.text) };
  }
  return query;
}

function rewritePortalSchemaArgs(args: unknown[]): unknown[] {
  const rewritten = [...args];
  if (rewritten.length > 0) rewritten[0] = rewritePortalSchemaQuery(rewritten[0]);
  return rewritten;
}

const pool = new Proxy(databasePool, {
  get(target, property) {
    if (property === "query") {
      return (...args: unknown[]) =>
        Reflect.apply(target.query, target, rewritePortalSchemaArgs(args));
    }
    if (property === "connect") {
      return async (...args: unknown[]) => {
        const client = await Reflect.apply(target.connect, target, args);
        return new Proxy(client, {
          get(clientTarget, clientProperty) {
            if (clientProperty === "query") {
              return (...queryArgs: unknown[]) =>
                Reflect.apply(
                  clientTarget.query,
                  clientTarget,
                  rewritePortalSchemaArgs(queryArgs),
                );
            }
            const value = Reflect.get(clientTarget, clientProperty, clientTarget);
            return typeof value === "function" ? value.bind(clientTarget) : value;
          },
        });
      };
    }
    const value = Reflect.get(target, property, target);
    return typeof value === "function" ? value.bind(target) : value;
  },
}) as typeof databasePool;
const SESSION_HOURS = 8;
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const LOGIN_MAX_ATTEMPTS = 8;
const loginFailures = new Map<string, { count: number; expiresAt: number }>();
const secretLike = /\b(?:password|passcode|otp|one[- ]time code|recovery code|secret key|api key)\b(?:\s+(?:is|:|=)\s*|[:=]\s*)\S+|\b(?:otp|one[- ]time code|recovery code)\s+\d{4,10}\b/i;
const dummyPasswordHash = hashPassword("synthetic-invalid-portal-account-password");

function noStore(_req: Request, res: Response, next: NextFunction): void {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  next();
}

function publicStaff(row: Record<string, unknown>) {
  return {
    staffId: String(row.id),
    email: String(row.email),
    displayName: String(row.display_name),
    role: row.role === "admin" || row.role === "owner"
      ? "owner"
      : row.role === "manager" || row.is_manager
        ? "manager"
        : "agent",
    active: Boolean(row.active),
    mustChangePassword: Boolean(row.must_change_password),
    created: String(row.created),
    lastLogin: row.last_login == null ? null : String(row.last_login),
  };
}

function publicReply(row: Record<string, unknown>) {
  return {
    replyId: String(row.id),
    caseId: String(row.case_id),
    responderName: String(row.responder_name),
    text: String(row.text),
    status: String(row.status) as "queued" | "sending" | "sent" | "uncertain" | "failed",
    created: String(row.created),
    updated: String(row.updated),
  };
}

function publicCase(row: Record<string, unknown>) {
  return {
    caseId: String(row.id),
    memberId: Number(row.user_id),
    question: String(row.question),
    status: String(row.status) as "open" | "reply_sending" | "reply_uncertain" | "replied" | "closed",
    workflowStatus: String(row.workflow_status ?? "new"),
    category: String(row.category ?? "unclassified"),
    priority: String(row.priority ?? "normal"),
    assignedStaffId: row.assigned_staff_id == null ? null : String(row.assigned_staff_id),
    created: String(row.created),
    updated: String(row.updated),
  };
}

function publicNote(row: Record<string, unknown>) {
  return {
    noteId: String(row.id),
    staffId: String(row.staff_id),
    responderName: String(row.responder_name),
    text: String(row.note),
    created: String(row.created),
  };
}

function publicCaseEvent(row: Record<string, unknown>) {
  return {
    eventId: String(row.id),
    actorName: String(row.actor_name ?? "Staff"),
    eventType: String(row.event_type),
    oldValue: String(row.old_value ?? ""),
    newValue: String(row.new_value ?? ""),
    created: String(row.created),
  };
}

function publicTask(row: Record<string, unknown>, events: Record<string, unknown>[] = []) {
  return {
    taskId: String(row.id),
    title: String(row.title),
    instructions: String(row.instructions),
    priority: String(row.priority),
    effortPoints: Number(row.effort_points ?? 1),
    dueAt: row.due_at == null ? null : String(row.due_at),
    teamId: row.team_id == null ? null : String(row.team_id),
    assignedStaffId: row.assigned_staff_id == null ? null : String(row.assigned_staff_id),
    assigneeName: row.assignee_name == null ? null : String(row.assignee_name),
    status: String(row.status),
    submissionNote: row.submission_note == null ? null : String(row.submission_note),
    reviewFeedback: row.review_feedback == null ? null : String(row.review_feedback),
    created: String(row.created),
    updated: String(row.updated),
    events: events.map((event) => ({
      eventId: String(event.id),
      actorName: String(event.actor_name ?? "Staff"),
      eventType: String(event.event_type),
      oldValue: String(event.old_value ?? ""),
      newValue: String(event.new_value ?? ""),
      feedback: String(event.feedback ?? ""),
      created: String(event.created),
    })),
  };
}

async function reportEvents(reportId: string, includeReviewerNames = false) {
  const result = await pool.query(
    `SELECT e.id,e.event_type,e.old_value,e.new_value,e.feedback,e.created,
            CASE WHEN $2::boolean OR e.event_type NOT IN ('reviewed','revision_requested')
                 THEN COALESCE(u.display_name,'Staff') ELSE 'Authorized reviewer' END AS actor_name
       FROM smh.staff_activity_report_events e
       LEFT JOIN smh.portal_users u ON u.id=e.actor_id
      WHERE e.report_id=$1 ORDER BY e.created`,
    [reportId,includeReviewerNames],
  );
  return result.rows;
}

function publicReport(
  row: Record<string, unknown>,
  events: Record<string, unknown>[] = [],
  includeReviewerName = false,
) {
  return {
    reportId: String(row.id),
    staffId: String(row.staff_id),
    staffName: String(row.staff_name ?? "Staff"),
    period: String(row.period),
    periodStart: String(row.period_start),
    completedWork: String(row.completed_work),
    outstandingWork: String(row.outstanding_work),
    blockers: String(row.blockers ?? ""),
    plans: String(row.plans ?? ""),
    reviewStatus: String(row.review_status),
    reviewedByName: includeReviewerName && row.reviewed_by_name != null
      ? String(row.reviewed_by_name) : null,
    reviewNote: String(row.review_note ?? ""),
    created: String(row.created),
    reviewedAt: row.reviewed_at == null ? null : String(row.reviewed_at),
    events: events.map((event) => ({
      eventId: String(event.id),
      actorName: String(event.actor_name ?? "Staff"),
      eventType: String(event.event_type),
      oldValue: String(event.old_value ?? ""),
      newValue: String(event.new_value ?? ""),
      feedback: String(event.feedback ?? ""),
      created: String(event.created),
    })),
  };
}

function publicReportNotification(row: Record<string, unknown>) {
  const reportId = String(row.report_id);
  return {
    notificationId: String(row.id),
    reportId,
    period: String(row.period),
    periodStart: String(row.period_start),
    outcome: String(row.outcome),
    reviewerFeedback: String(row.reviewer_feedback),
    href: `/tasks#report-${encodeURIComponent(reportId)}`,
    created: String(row.created),
    readAt: row.read_at == null ? null : String(row.read_at),
  };
}

async function taskEvents(taskId: string) {
  const result = await pool.query(
    `SELECT e.id,e.event_type,e.old_value,e.new_value,e.feedback,e.created,
            COALESCE(u.display_name,'Staff') AS actor_name
       FROM smh.staff_task_events e
       LEFT JOIN smh.portal_users u ON u.id=e.actor_id
      WHERE e.task_id=$1 ORDER BY e.created`,
    [taskId],
  );
  return result.rows;
}

async function visibleTask(taskId: string, identity: PortalIdentity) {
  const result = await pool.query(
    `SELECT t.*,u.display_name AS assignee_name,m.team_role
       FROM smh.staff_tasks t
       LEFT JOIN smh.portal_users u ON u.id=t.assigned_staff_id
       LEFT JOIN smh.staff_team_members m
         ON m.team_id=t.team_id AND m.staff_id=$2
      WHERE t.id=$1 AND (
        $3='owner'
        OR ($3='manager' AND m.team_role='manager')
        OR ($3='agent' AND (
          t.assigned_staff_id=$2
          OR (t.assigned_staff_id IS NULL AND m.team_role='worker')
        ))
      )`,
    [taskId, identity.id, identity.role],
  );
  return result.rows[0] as Record<string, unknown> | undefined;
}

async function addTaskEvent(
  client: { query: (sql: string, values?: unknown[]) => Promise<{ rows: Record<string, unknown>[] }> },
  taskId: string,
  actorId: string,
  eventType: string,
  oldValue: string,
  newValue: string,
  feedback: string,
  created: string,
) {
  const id = randomUUID();
  await client.query(
    `INSERT INTO smh.staff_task_events(id,task_id,actor_id,event_type,old_value,new_value,feedback,created)
     VALUES($1,$2,$3,$4,$5,$6,$7,$8)`,
    [id, taskId, actorId, eventType, oldValue, newValue, feedback, created],
  );
  return id;
}

async function addTaskNotification(
  client: { query: (sql: string, values?: unknown[]) => Promise<{ rows: Record<string, unknown>[] }> },
  recipientId: string,
  taskId: string,
  type: string,
  eventId: string,
  created: string,
) {
  await client.query(
    `INSERT INTO smh.staff_task_notifications(id,recipient_id,task_id,notification_type,dedupe_key,created)
     VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(dedupe_key) DO NOTHING`,
    [randomUUID(), recipientId, taskId, type, `${eventId}:${recipientId}`, created],
  );
}

function loginKey(req: Request, email: string): string {
  return createHash("sha256")
    .update(`${req.ip ?? "unknown"}:${email}`)
    .digest("hex");
}

function loginRateLimited(key: string): boolean {
  const current = loginFailures.get(key);
  if (!current || current.expiresAt <= Date.now()) {
    loginFailures.delete(key);
    return false;
  }
  return current.count >= LOGIN_MAX_ATTEMPTS;
}

function recordLoginFailure(key: string): void {
  const current = loginFailures.get(key);
  if (!current || current.expiresAt <= Date.now()) {
    if (loginFailures.size >= 5000) {
      for (const [oldKey, failure] of loginFailures) {
        if (failure.expiresAt <= Date.now()) loginFailures.delete(oldKey);
      }
      if (loginFailures.size >= 5000) {
        const oldest = loginFailures.keys().next().value;
        if (oldest) loginFailures.delete(oldest);
      }
    }
    loginFailures.set(key, { count: 1, expiresAt: Date.now() + LOGIN_WINDOW_MS });
  } else {
    current.count += 1;
  }
}

function clearLoginFailures(key: string): void {
  loginFailures.delete(key);
}

async function insertAudit(
  client: { query: (sql: string, values?: unknown[]) => Promise<unknown> },
  actorId: string,
  action: string,
  entityId: string,
  detail = "",
): Promise<void> {
  await client.query(
    `INSERT INTO smh.portal_audit(id,actor_id,action,entity_id,created,detail)
     VALUES($1,$2,$3,$4,$5,$6)`,
    [randomUUID(), actorId, action, entityId, new Date().toISOString(), detail],
  );
}

router.use("/portal", noStore);

router.post("/portal/auth/login", requireSameOrigin, async (req, res): Promise<void> => {
  const parsed = PortalLoginBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Enter a valid email and password." });
    return;
  }
  const email = parsed.data.email.trim().toLowerCase();
  const key = loginKey(req, email);
  if (loginRateLimited(key)) {
    res.status(429).json({ error: "Too many sign-in attempts. Wait a little and try again." });
    return;
  }
  const result = await pool.query(
    `SELECT u.id,u.email,u.display_name,u.password_hash,u.role,u.active,u.must_change_password,
            CASE WHEN u.role IN ('admin','owner') THEN 'owner'
                 WHEN u.role='manager' OR mr.staff_id IS NOT NULL THEN 'manager'
                 ELSE 'agent' END AS effective_role
       FROM smh.portal_users u
       LEFT JOIN smh.portal_manager_roles mr ON mr.staff_id=u.id
      WHERE lower(u.email)=$1`,
    [email],
  );
  const row = result.rows[0];
  const passwordMatches = verifyPassword(
    parsed.data.password,
    row ? String(row.password_hash) : dummyPasswordHash,
  );
  if (!row || !row.active || !passwordMatches) {
    recordLoginFailure(key);
    res.status(401).json({ error: "Email or password is incorrect." });
    return;
  }
  clearLoginFailures(key);
  const token = makeSessionToken();
  const tokenHash = hashSessionToken(token);
  const created = new Date().toISOString();
  const expires = new Date(Date.now() + SESSION_HOURS * 60 * 60 * 1000).toISOString();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      "INSERT INTO smh.portal_sessions(token_hash,staff_id,created,expires) VALUES($1,$2,$3,$4)",
      [tokenHash, row.id, created, expires],
    );
    await client.query(
      "UPDATE smh.portal_users SET last_login=$1,updated=$1 WHERE id=$2",
      [created, row.id],
    );
    await insertAudit(client, String(row.id), "signed_in", String(row.id));
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
  const identity: PortalIdentity = {
    id: String(row.id),
    email: String(row.email),
    displayName: String(row.display_name),
    role: row.effective_role as PortalIdentity["role"],
    mustChangePassword: Boolean(row.must_change_password),
  };
  setPortalSessionCookie(req, res, token);
  res.json(PortalLoginResponse.parse(toPortalSession(identity)));
});

router.use("/portal", requirePortalSession, requirePasswordReady);

router.get("/portal/auth/session", (req, res): void => {
  res.json(GetPortalSessionResponse.parse(toPortalSession(req.portalIdentity!)));
});

router.post("/portal/auth/logout", requireSameOrigin, async (req, res): Promise<void> => {
  if (req.portalSessionHash) {
    await pool.query("DELETE FROM smh.portal_sessions WHERE token_hash=$1", [req.portalSessionHash]);
  }
  clearPortalSessionCookie(req, res);
  res.json(PortalLogoutResponse.parse({ status: "signed_out" }));
});

router.post("/portal/auth/password", requireSameOrigin, async (req, res): Promise<void> => {
  const parsed = ChangePortalPasswordBody.safeParse(req.body);
  if (!parsed.success || parsed.data.newPassword.length < 12) {
    res.status(400).json({ error: "Choose a new password with at least 12 characters." });
    return;
  }
  const identity = req.portalIdentity!;
  const result = await pool.query(
    "SELECT password_hash FROM smh.portal_users WHERE id=$1 AND active=TRUE",
    [identity.id],
  );
  const row = result.rows[0];
  if (!row || !verifyPassword(parsed.data.currentPassword, String(row.password_hash))) {
    res.status(400).json({ error: "The current password is not correct." });
    return;
  }
  const updated = new Date().toISOString();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      "UPDATE smh.portal_users SET password_hash=$1,must_change_password=FALSE,updated=$2 WHERE id=$3",
      [hashPassword(parsed.data.newPassword), updated, identity.id],
    );
    await client.query(
      "DELETE FROM smh.portal_sessions WHERE staff_id=$1 AND token_hash<>$2",
      [identity.id, req.portalSessionHash],
    );
    await insertAudit(client, identity.id, "password_changed", identity.id);
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
  res.json(ChangePortalPasswordResponse.parse({ ...toPortalSession(identity), mustChangePassword: false }));
});

router.get("/portal/tasks", async (req, res): Promise<void> => {
  const identity = req.portalIdentity!;
  const result = await pool.query(
    `SELECT t.*,u.display_name AS assignee_name
       FROM smh.staff_tasks t
       LEFT JOIN smh.portal_users u ON u.id=t.assigned_staff_id
      WHERE $1='owner'
         OR ($1='manager' AND EXISTS (
              SELECT 1 FROM smh.staff_team_members m
               WHERE m.team_id=t.team_id AND m.staff_id=$2 AND m.team_role='manager'))
         OR ($1='agent' AND (
              t.assigned_staff_id=$2 OR (t.assigned_staff_id IS NULL AND EXISTS (
                SELECT 1 FROM smh.staff_team_members m
                 WHERE m.team_id=t.team_id AND m.staff_id=$2 AND m.team_role='worker'))))
      ORDER BY t.due_at NULLS LAST,t.updated DESC`,
    [identity.role, identity.id],
  );
  const taskRows = await Promise.all(result.rows.map(async (row) =>
    publicTask(row, await taskEvents(String(row.id)))));
  res.json(ListStaffTasksResponse.parse({ tasks: taskRows }));
});

router.post("/portal/tasks", requireSameOrigin, async (req, res): Promise<void> => {
  const identity = req.portalIdentity!;
  if (identity.role !== "owner") {
    res.status(403).json({ error: "Only the owner can create and assign tasks." });
    return;
  }
  const parsed = CreateStaffTaskBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Check the task details and try again." });
    return;
  }
  const input = parsed.data;
  const title = input.title.trim();
  const instructions = input.instructions.trim();
  const now = new Date().toISOString();
  if (!title || !instructions || (!input.teamId && !input.assignedStaffId)
    || (input.dueAt && (!Number.isFinite(input.dueAt.getTime()) || input.dueAt.getTime() < Date.now()))) {
    res.status(400).json({ error: "Provide a task title, instructions, an assignee or team, and a future deadline." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const prior = await client.query(
      "SELECT id FROM smh.staff_tasks WHERE created_by=$1 AND request_id=$2",
      [identity.id, input.requestId],
    );
    if (prior.rows[0]) {
      await client.query("COMMIT");
      const existing = await visibleTask(String(prior.rows[0].id), identity);
      res.status(200).json(CreateStaffTaskResponse.parse(publicTask(existing ?? {})));
      return;
    }
    if (input.teamId) {
      const team = await client.query(
        `SELECT id,EXISTS(SELECT 1 FROM smh.staff_team_members
                         WHERE team_id=$1 AND team_role='worker') AS has_worker
           FROM smh.staff_teams WHERE id=$1`,
        [input.teamId],
      );
      if (!team.rows[0]) {
        await client.query("ROLLBACK");
        res.status(400).json({ error: "Select a team that exists." });
        return;
      }
      if (!input.assignedStaffId && !team.rows[0].has_worker) {
        await client.query("ROLLBACK");
        res.status(400).json({ error: "Add at least one worker to this team before assigning a team task." });
        return;
      }
    }
    if (input.assignedStaffId) {
      const assignee = await client.query(
        `SELECT u.id FROM smh.portal_users u
          WHERE u.id=$1 AND u.active=TRUE AND u.role='agent'
            AND NOT EXISTS (SELECT 1 FROM smh.portal_manager_roles mr WHERE mr.staff_id=u.id)`,
        [input.assignedStaffId],
      );
      if (!assignee.rows[0]) {
        await client.query("ROLLBACK");
        res.status(400).json({ error: "Choose an active Support Agent as the individual assignee." });
        return;
      }
      if (input.teamId) {
        const member = await client.query(
          "SELECT 1 FROM smh.staff_team_members WHERE team_id=$1 AND staff_id=$2 AND team_role='worker'",
          [input.teamId, input.assignedStaffId],
        );
        if (!member.rows[0]) {
          await client.query("ROLLBACK");
          res.status(400).json({ error: "An individually assigned worker must belong to the selected team." });
          return;
        }
      }
    }
    const taskId = randomUUID();
    const created = now;
    await client.query(
      `INSERT INTO smh.staff_tasks
         (id,request_id,title,instructions,priority,effort_points,due_at,team_id,assigned_staff_id,status,created_by,created,updated)
       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'assigned',$10,$11,$11)`,
      [taskId, input.requestId, title, instructions, input.priority, input.effortPoints,
       input.dueAt?.toISOString() ?? null, input.teamId, input.assignedStaffId, identity.id, created],
    );
    await addTaskEvent(client, taskId, identity.id, "task_created", "", "assigned", "", created);
    const eventId = await addTaskEvent(client, taskId, identity.id, "task_assigned", "",
      input.assignedStaffId ?? input.teamId ?? "", "", created);
    const recipients = input.assignedStaffId
      ? [input.assignedStaffId]
      : (await client.query(
          "SELECT staff_id FROM smh.staff_team_members WHERE team_id=$1 AND team_role='worker'",
          [input.teamId],
        )).rows.map((row) => String(row.staff_id));
    for (const recipient of recipients) {
      await addTaskNotification(client, recipient, taskId, "assigned", eventId, created);
    }
    await insertAudit(client, identity.id, "task_created", taskId, eventId);
    await client.query("COMMIT");
    const createdTask = await visibleTask(taskId, identity);
    res.status(201).json(CreateStaffTaskResponse.parse(publicTask(createdTask ?? {})));
  } catch (error) {
    await client.query("ROLLBACK");
    if (typeof error === "object" && error !== null && "code" in error && error.code === "23505") {
      const prior = await pool.query(
        "SELECT id FROM smh.staff_tasks WHERE created_by=$1 AND request_id=$2",
        [identity.id, input.requestId],
      );
      const existing = prior.rows[0] ? await visibleTask(String(prior.rows[0].id), identity) : undefined;
      if (existing) {
        res.status(200).json(CreateStaffTaskResponse.parse(publicTask(existing)));
        return;
      }
    }
    throw error;
  } finally {
    client.release();
  }
});

router.get("/portal/tasks/:taskId", async (req, res): Promise<void> => {
  const params = GetStaffTaskParams.safeParse(req.params);
  if (!params.success) {
    res.status(404).json({ error: "Task not found or not accessible." });
    return;
  }
  const row = await visibleTask(params.data.taskId, req.portalIdentity!);
  if (!row) {
    res.status(404).json({ error: "Task not found or not accessible." });
    return;
  }
  res.json(GetStaffTaskResponse.parse(publicTask(row, await taskEvents(params.data.taskId))));
});

router.patch("/portal/tasks/:taskId", requireSameOrigin, async (req, res): Promise<void> => {
  const params = UpdateStaffTaskParams.safeParse(req.params);
  const parsed = UpdateStaffTaskBody.safeParse(req.body);
  const identity = req.portalIdentity!;
  if (identity.role !== "owner") {
    res.status(403).json({ error: "Only the owner can edit or reassign tasks." });
    return;
  }
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Check the task details and try again." });
    return;
  }
  const input = parsed.data;
  const title = input.title.trim();
  const instructions = input.instructions.trim();
  const dueAt = input.dueAt?.toISOString() ?? null;
  if (!title || !instructions || (!input.teamId && !input.assignedStaffId)
    || (dueAt && Date.parse(dueAt) < Date.now())) {
    res.status(400).json({ error: "Provide task details, an assignee or team, and a future deadline." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await client.query(
      "SELECT * FROM smh.staff_tasks WHERE id=$1 FOR UPDATE",
      [params.data.taskId],
    );
    const current = result.rows[0] as Record<string, unknown> | undefined;
    if (!current) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "Task not found." });
      return;
    }
    const old = {
      title: String(current.title),
      instructions: String(current.instructions),
      priority: String(current.priority),
      effortPoints: Number(current.effort_points ?? 1),
      dueAt: current.due_at == null ? null : new Date(String(current.due_at)).toISOString(),
      teamId: current.team_id == null ? null : String(current.team_id),
      assignedStaffId: current.assigned_staff_id == null ? null : String(current.assigned_staff_id),
    };
    const next = {
      title, instructions, priority: input.priority, effortPoints: input.effortPoints,
      dueAt, teamId: input.teamId, assignedStaffId: input.assignedStaffId,
    };
    if (JSON.stringify(old) === JSON.stringify(next)) {
      await client.query("COMMIT");
      const unchanged = await visibleTask(params.data.taskId, identity);
      res.json(UpdateStaffTaskResponse.parse(
        publicTask(unchanged ?? {}, await taskEvents(params.data.taskId)),
      ));
      return;
    }
    if (String(current.updated) !== input.expectedUpdatedAt) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This task changed since you opened it. Refresh and review the latest version." });
      return;
    }
    if (["submitted_for_review", "approved", "cancelled"].includes(String(current.status))) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "Review or reopen the task before changing its assignment or instructions." });
      return;
    }
    if (input.teamId) {
      const team = await client.query(
        `SELECT EXISTS(SELECT 1 FROM smh.staff_team_members
                       WHERE team_id=$1 AND team_role='worker') AS has_worker
          FROM smh.staff_teams WHERE id=$1`,
        [input.teamId],
      );
      if (!team.rows[0]) {
        await client.query("ROLLBACK");
        res.status(400).json({ error: "Select a team that exists." });
        return;
      }
      if (!input.assignedStaffId && !team.rows[0].has_worker) {
        await client.query("ROLLBACK");
        res.status(400).json({ error: "Add at least one worker to the team before assigning a team task." });
        return;
      }
    }
    if (input.assignedStaffId) {
      const assignee = await client.query(
        `SELECT 1 FROM smh.portal_users u
          WHERE u.id=$1 AND u.active=TRUE AND u.role='agent'
            AND NOT EXISTS(SELECT 1 FROM smh.portal_manager_roles mr WHERE mr.staff_id=u.id)`,
        [input.assignedStaffId],
      );
      if (!assignee.rows[0]) {
        await client.query("ROLLBACK");
        res.status(400).json({ error: "Choose an active Support Agent as the individual assignee." });
        return;
      }
      if (input.teamId) {
        const membership = await client.query(
          "SELECT 1 FROM smh.staff_team_members WHERE team_id=$1 AND staff_id=$2 AND team_role='worker'",
          [input.teamId, input.assignedStaffId],
        );
        if (!membership.rows[0]) {
          await client.query("ROLLBACK");
          res.status(400).json({ error: "The individually assigned worker must belong to the selected team." });
          return;
        }
      }
    }
    const updated = new Date().toISOString();
    await client.query(
      `UPDATE smh.staff_tasks
          SET title=$1,instructions=$2,priority=$3,effort_points=$4,due_at=$5,
              team_id=$6,assigned_staff_id=$7,updated=$8
        WHERE id=$9`,
      [next.title,next.instructions,next.priority,next.effortPoints,next.dueAt,
       next.teamId,next.assignedStaffId,updated,params.data.taskId],
    );
    const changes = Object.fromEntries(Object.keys(next)
      .filter((key) => old[key as keyof typeof old] !== next[key as keyof typeof next])
      .map((key) => [key, { from: old[key as keyof typeof old], to: next[key as keyof typeof next] }]));
    const eventId = await addTaskEvent(client, params.data.taskId, identity.id,
      "task_edited", JSON.stringify(old), JSON.stringify(next), "", updated);
    const assignmentChanged = old.teamId !== next.teamId || old.assignedStaffId !== next.assignedStaffId;
    if (assignmentChanged || old.dueAt !== next.dueAt) {
      const recipients = next.assignedStaffId
        ? [next.assignedStaffId]
        : (await client.query(
            "SELECT staff_id FROM smh.staff_team_members WHERE team_id=$1 AND team_role='worker'",
            [next.teamId],
          )).rows.map((row) => String(row.staff_id));
      const notificationType = assignmentChanged ? "reassigned" : "deadline_changed";
      for (const recipient of recipients) {
        await addTaskNotification(client, recipient, params.data.taskId, notificationType, eventId, updated);
      }
    }
    await insertAudit(client, identity.id, "task_edited", params.data.taskId, JSON.stringify(changes));
    await client.query("COMMIT");
    const updatedTask = await visibleTask(params.data.taskId, identity);
    res.json(UpdateStaffTaskResponse.parse(publicTask(updatedTask ?? {}, await taskEvents(params.data.taskId))));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.patch("/portal/tasks/:taskId/status", requireSameOrigin, async (req, res): Promise<void> => {
  const params = UpdateStaffTaskStatusParams.safeParse(req.params);
  const parsed = UpdateStaffTaskStatusBody.safeParse(req.body);
  const identity = req.portalIdentity!;
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Check the status update and try again." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const currentResult = await client.query(
      `SELECT t.*,u.display_name AS assignee_name,m.team_role
         FROM smh.staff_tasks t
         LEFT JOIN smh.portal_users u ON u.id=t.assigned_staff_id
         LEFT JOIN smh.staff_team_members m ON m.team_id=t.team_id AND m.staff_id=$2
        WHERE t.id=$1 FOR UPDATE OF t`,
      [params.data.taskId, identity.id],
    );
    const current = currentResult.rows[0] as Record<string, unknown> | undefined;
    if (!current || !canAccessStaffTask(identity.role, identity.id, {
      teamId: current.team_id == null ? null : String(current.team_id),
      assignedStaffId: current.assigned_staff_id == null ? null : String(current.assigned_staff_id),
    }, current.team_role === "manager" || current.team_role === "worker" ? current.team_role : null)) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "Task not found or not accessible." });
      return;
    }
    const oldStatus = String(current.status) as StaffTaskStatus;
    const nextStatus = parsed.data.status as StaffTaskStatus;
    const teamManager = current.team_role === "manager";
    const workerAccess = identity.id === String(current.assigned_staff_id ?? "")
      || (current.assigned_staff_id == null && current.team_role === "worker");
    if (oldStatus === nextStatus) {
      await client.query("COMMIT");
      res.json(UpdateStaffTaskStatusResponse.parse(publicTask(current, await taskEvents(params.data.taskId))));
      return;
    }
    if (!mayChangeTaskStatus(identity.role, oldStatus, nextStatus, teamManager, workerAccess)) {
      await client.query("ROLLBACK");
      res.status(403).json({ error: "You do not have permission to make that task status change." });
      return;
    }
    const note = parsed.data.note.trim();
    if ((nextStatus === "submitted_for_review" || nextStatus === "revision_requested") && note.length < 3) {
      await client.query("ROLLBACK");
      res.status(400).json({ error: "Add a short completion note or revision instruction before submitting." });
      return;
    }
    if (nextStatus === "approved" && identity.id === String(current.assigned_staff_id ?? "")) {
      await client.query("ROLLBACK");
      res.status(403).json({ error: "A worker cannot approve their own work." });
      return;
    }
    const created = new Date().toISOString();
    await client.query(
      `UPDATE smh.staff_tasks
          SET status=$1,updated=$2,
              submission_note=CASE WHEN $1='submitted_for_review' THEN $3
                                   WHEN $1='in_progress' THEN NULL ELSE submission_note END,
              review_feedback=CASE WHEN $1='revision_requested' THEN $3
                                   WHEN $1='approved' THEN '' ELSE review_feedback END
        WHERE id=$4`,
      [nextStatus, created, note, params.data.taskId],
    );
    const eventId = await addTaskEvent(client, params.data.taskId, identity.id, "status_changed",
      oldStatus, nextStatus, note, created);
    if (current.assigned_staff_id
      && ["revision_requested", "approved", "cancelled"].includes(nextStatus)) {
      await addTaskNotification(client, String(current.assigned_staff_id), params.data.taskId, nextStatus, eventId, created);
    }
    if (nextStatus === "submitted_for_review") {
      const reviewers = await client.query(
        `SELECT DISTINCT id FROM smh.portal_users
          WHERE active=TRUE AND (role IN ('admin','owner') OR id IN (
            SELECT staff_id FROM smh.staff_team_members WHERE team_id=$1 AND team_role='manager'
          ))`,
        [current.team_id],
      );
      for (const reviewer of reviewers.rows) {
        await addTaskNotification(client, String(reviewer.id), params.data.taskId, nextStatus, eventId, created);
      }
    } else if (!current.assigned_staff_id && current.team_id
      && ["revision_requested", "approved", "cancelled"].includes(nextStatus)) {
      const members = await client.query(
        `SELECT staff_id FROM smh.staff_team_members WHERE team_id=$1
         AND team_role=CASE WHEN $2='submitted_for_review' THEN 'manager' ELSE 'worker' END`,
        [current.team_id, nextStatus],
      );
      for (const member of members.rows) {
        await addTaskNotification(client, String(member.staff_id), params.data.taskId, nextStatus, eventId, created);
      }
    }
    await insertAudit(client, identity.id, "task_status_changed", params.data.taskId, eventId);
    await client.query("COMMIT");
    const updated = await visibleTask(params.data.taskId, identity);
    res.json(UpdateStaffTaskStatusResponse.parse(publicTask(updated ?? {}, await taskEvents(params.data.taskId))));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.get("/portal/activity-reports", async (req, res): Promise<void> => {
  const identity = req.portalIdentity!;
  const result = await pool.query(
    `SELECT r.*,u.display_name AS staff_name,reviewer.display_name AS reviewed_by_name
       FROM smh.staff_activity_reports r
       JOIN smh.portal_users u ON u.id=r.staff_id
       LEFT JOIN smh.portal_users reviewer ON reviewer.id=r.reviewed_by
      WHERE ($1='owner' OR r.staff_id=$2 OR ($1='manager' AND EXISTS (
        SELECT 1 FROM smh.staff_team_members manager
        JOIN smh.staff_team_members worker ON worker.team_id=manager.team_id
        WHERE manager.staff_id=$2 AND manager.team_role='manager'
          AND worker.staff_id=r.staff_id AND worker.team_role='worker'
      )))
      ORDER BY r.period_start DESC,r.created DESC LIMIT 200`,
    [identity.role, identity.id],
  );
  const includeReviewerNames = identity.role !== "agent";
  const reports = await Promise.all(result.rows.map(async (row) =>
    publicReport(row, await reportEvents(String(row.id),includeReviewerNames),includeReviewerNames)));
  res.json(ListStaffActivityReportsResponse.parse({ reports }));
});

router.post("/portal/activity-reports", requireSameOrigin, async (req, res): Promise<void> => {
  const parsed = SubmitStaffActivityReportBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Complete the required report fields and try again." });
    return;
  }
  const input = parsed.data;
  const periodStart = input.periodStart.toISOString().slice(0, 10);
  if (!Number.isFinite(input.periodStart.getTime())
    || periodStart > new Date().toISOString().slice(0, 10)) {
    res.status(400).json({ error: "Choose a valid report date that is not in the future." });
    return;
  }
  if (input.period === "weekly" && input.periodStart.getUTCDay() !== 1) {
    res.status(400).json({ error: "A weekly report must start on a Monday." });
    return;
  }
  const identity = req.portalIdentity!;
  const client = await pool.connect();
  let reportId = "";
  let statusCode = 201;
  try {
    await client.query("BEGIN");
    const existing = await client.query(
      `SELECT id,review_status FROM smh.staff_activity_reports
        WHERE staff_id=$1 AND period=$2 AND period_start=$3 FOR UPDATE`,
      [identity.id, input.period, periodStart],
    );
    const now = new Date().toISOString();
    if (existing.rows[0]) {
      reportId = String(existing.rows[0].id);
      if (String(existing.rows[0].review_status) === "revision_requested") {
        statusCode = 200;
        await client.query(
          `UPDATE smh.staff_activity_reports
              SET completed_work=$1,outstanding_work=$2,blockers=$3,plans=$4,
                  review_status='submitted',reviewed_by=NULL,review_note='',reviewed_at=NULL,created=$5
            WHERE id=$6`,
          [input.completedWork.trim(),input.outstandingWork.trim(),input.blockers.trim(),input.plans.trim(),now,reportId],
        );
        await client.query(
          `INSERT INTO smh.staff_activity_report_events(id,report_id,actor_id,event_type,old_value,new_value,feedback,created)
           VALUES($1,$2,$3,'resubmitted','revision_requested','submitted','',$4)`,
          [randomUUID(),reportId,identity.id,now],
        );
        await insertAudit(client, identity.id, "activity_report_resubmitted", reportId);
      } else {
        statusCode = 200;
      }
    } else {
      reportId = randomUUID();
      await client.query(
        `INSERT INTO smh.staff_activity_reports
           (id,staff_id,period,period_start,completed_work,outstanding_work,blockers,plans,review_status,created)
         VALUES($1,$2,$3,$4,$5,$6,$7,$8,'submitted',$9)`,
        [reportId,identity.id,input.period,periodStart,input.completedWork.trim(),
         input.outstandingWork.trim(),input.blockers.trim(),input.plans.trim(),now],
      );
      await client.query(
        `INSERT INTO smh.staff_activity_report_events(id,report_id,actor_id,event_type,old_value,new_value,feedback,created)
         VALUES($1,$2,$3,'submitted','','submitted','',$4)`,
        [randomUUID(),reportId,identity.id,now],
      );
      await insertAudit(client, identity.id, "activity_report_submitted", reportId);
    }
    await client.query("COMMIT");
    const saved = await pool.query(
      `SELECT r.*,u.display_name AS staff_name,reviewer.display_name AS reviewed_by_name
         FROM smh.staff_activity_reports r JOIN smh.portal_users u ON u.id=r.staff_id
         LEFT JOIN smh.portal_users reviewer ON reviewer.id=r.reviewed_by WHERE r.id=$1`,
      [reportId],
    );
    res.status(statusCode).json(SubmitStaffActivityReportResponse.parse(
      publicReport(saved.rows[0], await reportEvents(reportId)),
    ));
  } catch (error) {
    await client.query("ROLLBACK");
    if (typeof error === "object" && error !== null && "code" in error && error.code === "23505") {
      const concurrent = await pool.query(
        `SELECT r.*,u.display_name AS staff_name,reviewer.display_name AS reviewed_by_name
           FROM smh.staff_activity_reports r JOIN smh.portal_users u ON u.id=r.staff_id
           LEFT JOIN smh.portal_users reviewer ON reviewer.id=r.reviewed_by
          WHERE r.staff_id=$1 AND r.period=$2 AND r.period_start=$3`,
        [identity.id,input.period,periodStart],
      );
      if (concurrent.rows[0]) {
        const saved = concurrent.rows[0];
        res.status(200).json(SubmitStaffActivityReportResponse.parse(
          publicReport(saved, await reportEvents(String(saved.id))),
        ));
        return;
      }
      res.status(409).json({ error: "A report for this period already exists. Refresh and review it." });
      return;
    }
    throw error;
  } finally {
    client.release();
  }
});

router.patch("/portal/activity-reports/:reportId/review", requireSameOrigin, async (req, res): Promise<void> => {
  const params = ReviewStaffActivityReportParams.safeParse(req.params);
  const parsed = ReviewStaffActivityReportBody.safeParse(req.body);
  const identity = req.portalIdentity!;
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Add a clear review note and choose an action." });
    return;
  }
  if (identity.role !== "owner" && identity.role !== "manager") {
    res.status(403).json({ error: "Only an authorized owner or team manager can review reports." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await client.query(
      "SELECT r.* FROM smh.staff_activity_reports r WHERE r.id=$1 FOR UPDATE",
      [params.data.reportId],
    );
    const report = result.rows[0] as Record<string, unknown> | undefined;
    if (!report) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "Report not found or not accessible." });
      return;
    }
    const staffId = String(report.staff_id);
    if (staffId === identity.id) {
      await client.query("ROLLBACK");
      res.status(403).json({ error: "You cannot review your own report." });
      return;
    }
    if (identity.role === "manager") {
      const authorized = await client.query(
        `SELECT 1 FROM smh.staff_team_members manager
          JOIN smh.staff_team_members worker ON worker.team_id=manager.team_id
         WHERE manager.staff_id=$1 AND manager.team_role='manager'
           AND worker.staff_id=$2 AND worker.team_role='worker' LIMIT 1`,
        [identity.id, staffId],
      );
      if (!authorized.rows[0]) {
        await client.query("ROLLBACK");
        res.status(404).json({ error: "Report not found or not accessible." });
        return;
      }
    }
    if (String(report.review_status) !== "submitted") {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "Only a submitted report can be reviewed. Resubmit requested revisions first." });
      return;
    }
    const now = new Date().toISOString();
    await client.query(
      `UPDATE smh.staff_activity_reports SET review_status=$1,reviewed_by=$2,review_note=$3,reviewed_at=$4 WHERE id=$5`,
      [parsed.data.status,identity.id,parsed.data.note.trim(),now,params.data.reportId],
    );
    const reportEventId = randomUUID();
    await client.query(
      `INSERT INTO smh.staff_activity_report_events(id,report_id,actor_id,event_type,old_value,new_value,feedback,created)
       VALUES($1,$2,$3,$4,'submitted',$5,$6,$7)`,
      [reportEventId,params.data.reportId,identity.id,parsed.data.status,parsed.data.status,parsed.data.note.trim(),now],
    );
    const outcome = parsed.data.status === "reviewed" ? "approved" : "revision_requested";
    await client.query(
      `INSERT INTO smh.staff_report_notifications
         (id,recipient_id,report_id,report_event_id,outcome,reviewer_feedback,dedupe_key,created)
       VALUES($1,$2,$3,$4,$5,$6,$7,$8)
       ON CONFLICT(dedupe_key) DO NOTHING`,
      [randomUUID(),staffId,params.data.reportId,reportEventId,outcome,parsed.data.note.trim(),
       `report-review:${params.data.reportId}:${reportEventId}:${staffId}`,now],
    );
    await insertAudit(client, identity.id, `activity_report_${parsed.data.status}`, params.data.reportId);
    await client.query("COMMIT");
    const updated = await pool.query(
      `SELECT r.*,u.display_name AS staff_name,reviewer.display_name AS reviewed_by_name
         FROM smh.staff_activity_reports r JOIN smh.portal_users u ON u.id=r.staff_id
         LEFT JOIN smh.portal_users reviewer ON reviewer.id=r.reviewed_by WHERE r.id=$1`,
      [params.data.reportId],
    );
    res.json(ReviewStaffActivityReportResponse.parse(
      publicReport(updated.rows[0], await reportEvents(params.data.reportId,true),true),
    ));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.get("/portal/performance", async (req, res): Promise<void> => {
  const identity = req.portalIdentity!;
  const metrics = await pool.query(
    `WITH visible_staff AS (
       SELECT u.id,u.display_name
         FROM smh.portal_users u
        WHERE u.active AND u.role='agent'
          AND ($1='owner' OR u.id=$2 OR ($1='manager' AND EXISTS (
            SELECT 1 FROM smh.staff_team_members manager
            JOIN smh.staff_team_members worker ON worker.team_id=manager.team_id
            WHERE manager.staff_id=$2 AND manager.team_role='manager'
              AND worker.staff_id=u.id AND worker.team_role='worker'
          )))
     )
     SELECT s.id AS staff_id,s.display_name AS staff_name,
       (SELECT count(*)::int FROM smh.staff_tasks t WHERE
         (t.assigned_staff_id=s.id OR (t.assigned_staff_id IS NULL AND EXISTS(
           SELECT 1 FROM smh.staff_team_members m WHERE m.team_id=t.team_id AND m.staff_id=s.id AND m.team_role='worker'
         ))) AND t.status NOT IN ('approved','cancelled')) AS active_tasks,
       (SELECT COALESCE(sum(t.effort_points),0)::int FROM smh.staff_tasks t WHERE
         (t.assigned_staff_id=s.id OR (t.assigned_staff_id IS NULL AND EXISTS(
           SELECT 1 FROM smh.staff_team_members m WHERE m.team_id=t.team_id AND m.staff_id=s.id AND m.team_role='worker'
         ))) AND t.status NOT IN ('approved','cancelled')) AS active_effort_points,
       (SELECT count(*)::int FROM smh.staff_tasks t WHERE
         (t.assigned_staff_id=s.id OR (t.assigned_staff_id IS NULL AND EXISTS(
           SELECT 1 FROM smh.staff_team_members m WHERE m.team_id=t.team_id AND m.staff_id=s.id AND m.team_role='worker'
         ))) AND t.status='approved') AS approved_tasks,
       (SELECT COALESCE(sum(t.effort_points),0)::int FROM smh.staff_tasks t WHERE
         (t.assigned_staff_id=s.id OR (t.assigned_staff_id IS NULL AND EXISTS(
           SELECT 1 FROM smh.staff_team_members m WHERE m.team_id=t.team_id AND m.staff_id=s.id AND m.team_role='worker'
         ))) AND t.status='approved') AS approved_effort_points,
       (SELECT count(*)::int FROM smh.staff_tasks t WHERE
         (t.assigned_staff_id=s.id OR (t.assigned_staff_id IS NULL AND EXISTS(
           SELECT 1 FROM smh.staff_team_members m WHERE m.team_id=t.team_id AND m.staff_id=s.id AND m.team_role='worker'
         ))) AND t.status NOT IN ('approved','cancelled') AND t.due_at::timestamptz<now()) AS overdue_tasks,
       (SELECT count(*)::int FROM smh.staff_tasks t WHERE
         (t.assigned_staff_id=s.id OR (t.assigned_staff_id IS NULL AND EXISTS(
           SELECT 1 FROM smh.staff_team_members m WHERE m.team_id=t.team_id AND m.staff_id=s.id AND m.team_role='worker'
         ))) AND t.status='approved' AND (t.due_at IS NULL OR t.updated::timestamptz<=t.due_at::timestamptz)) AS on_time_approvals,
       (SELECT count(*)::int FROM smh.staff_task_events e JOIN smh.staff_tasks t ON t.id=e.task_id
         WHERE e.event_type='status_changed' AND e.new_value='revision_requested' AND
           (t.assigned_staff_id=s.id OR (t.assigned_staff_id IS NULL AND EXISTS(
             SELECT 1 FROM smh.staff_team_members m WHERE m.team_id=t.team_id AND m.staff_id=s.id AND m.team_role='worker'
           )))) AS revision_requests,
       (SELECT count(*)::int FROM ${supportSchema}.assistant_escalations c WHERE c.assigned_staff_id=s.id) AS support_cases,
       (SELECT count(*)::int FROM ${supportSchema}.assistant_escalations c
         WHERE c.assigned_staff_id=s.id AND c.workflow_status NOT IN ('resolved','closed')) AS open_support_cases,
       (SELECT count(*)::int FROM ${supportSchema}.assistant_support_replies r
         WHERE r.staff_id=s.id AND r.status='sent') AS support_replies
     FROM visible_staff s ORDER BY s.display_name`,
    [identity.role, identity.id],
  );
  res.json(GetStaffPerformanceResponse.parse({
    generatedAt: new Date().toISOString(),
    metrics: metrics.rows.map((row) => ({
      staffId: String(row.staff_id), staffName: String(row.staff_name),
      activeTasks: Number(row.active_tasks), activeEffortPoints: Number(row.active_effort_points),
      approvedTasks: Number(row.approved_tasks), approvedEffortPoints: Number(row.approved_effort_points),
      overdueTasks: Number(row.overdue_tasks), onTimeApprovals: Number(row.on_time_approvals),
      revisionRequests: Number(row.revision_requests), supportCases: Number(row.support_cases),
      openSupportCases: Number(row.open_support_cases), supportReplies: Number(row.support_replies),
    })),
  }));
});

router.get("/portal/teams", async (req, res): Promise<void> => {
  const identity = req.portalIdentity!;
  const teams = await pool.query(
    `SELECT t.id,t.name FROM smh.staff_teams t
      WHERE $1='owner' OR EXISTS (
        SELECT 1 FROM smh.staff_team_members m
         WHERE m.team_id=t.id AND m.staff_id=$2
           AND (($1='manager' AND m.team_role='manager') OR ($1='agent' AND m.team_role='worker')))
      ORDER BY t.name`,
    [identity.role, identity.id],
  );
  const mapped = [];
  for (const team of teams.rows) {
    const members = await pool.query(
      `SELECT m.staff_id,u.display_name,m.team_role
         FROM smh.staff_team_members m JOIN smh.portal_users u ON u.id=m.staff_id
        WHERE m.team_id=$1 ORDER BY u.display_name`,
      [team.id],
    );
    mapped.push({
      teamId: String(team.id), name: String(team.name),
      members: members.rows.map((member) => ({
        staffId: String(member.staff_id), displayName: String(member.display_name), teamRole: String(member.team_role),
      })),
    });
  }
  res.json(ListStaffTeamsResponse.parse({ teams: mapped }));
});

router.post("/portal/teams", requireSameOrigin, async (req, res): Promise<void> => {
  const identity = req.portalIdentity!;
  const parsed = CreateStaffTeamBody.safeParse(req.body);
  const name = parsed.success ? parsed.data.name.trim().replace(/\s+/g, " ") : "";
  if (identity.role !== "owner") {
    res.status(403).json({ error: "Only the owner can create teams." });
    return;
  }
  if (!parsed.success || name.length < 2 || name.length > 80) {
    res.status(400).json({ error: "Enter a team name between 2 and 80 characters." });
    return;
  }
  const id = randomUUID();
  const created = new Date().toISOString();
  try {
    await pool.query("INSERT INTO smh.staff_teams(id,name,created_by,created) VALUES($1,$2,$3,$4)",
      [id, name, identity.id, created]);
  } catch (error) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "23505") {
      res.status(409).json({ error: "A team with that name already exists." });
      return;
    }
    throw error;
  }
  res.status(201).json(CreateStaffTeamResponse.parse({ teamId: id, name, members: [] }));
});

router.put("/portal/teams/:teamId/members", requireSameOrigin, async (req, res): Promise<void> => {
  const identity = req.portalIdentity!;
  const params = SetStaffTeamMembersParams.safeParse(req.params);
  const parsed = SetStaffTeamMembersBody.safeParse(req.body);
  if (identity.role !== "owner") {
    res.status(403).json({ error: "Only the owner can change team access." });
    return;
  }
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Check the team members and try again." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const team = await client.query("SELECT id,name FROM smh.staff_teams WHERE id=$1 FOR UPDATE",
      [params.data.teamId]);
    if (!team.rows[0]) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "Team not found." });
      return;
    }
    for (const member of parsed.data.members) {
      const account = await client.query(
        `SELECT u.id FROM smh.portal_users u
          WHERE u.id=$1 AND u.active=TRUE
            AND (($2='manager' AND (u.role='manager' OR EXISTS (
                    SELECT 1 FROM smh.portal_manager_roles mr WHERE mr.staff_id=u.id)))
              OR ($2='worker' AND u.role='agent' AND NOT EXISTS (
                SELECT 1 FROM smh.portal_manager_roles mr WHERE mr.staff_id=u.id)))`,
        [member.staffId, member.teamRole],
      );
      if (!account.rows[0]) {
        await client.query("ROLLBACK");
        res.status(400).json({ error: "Each team member must be active and match the selected role." });
        return;
      }
    }
    await client.query("DELETE FROM smh.staff_team_members WHERE team_id=$1", [params.data.teamId]);
    for (const member of parsed.data.members) {
      await client.query(
        "INSERT INTO smh.staff_team_members(team_id,staff_id,team_role,created) VALUES($1,$2,$3,$4)",
        [params.data.teamId, member.staffId, member.teamRole, new Date().toISOString()],
      );
    }
    const members = await client.query(
      `SELECT m.staff_id,u.display_name,m.team_role FROM smh.staff_team_members m
       JOIN smh.portal_users u ON u.id=m.staff_id WHERE m.team_id=$1 ORDER BY u.display_name`,
      [params.data.teamId],
    );
    await client.query("COMMIT");
    res.json(SetStaffTeamMembersResponse.parse({
      teamId: String(team.rows[0].id),
      name: String(team.rows[0].name),
      members: members.rows.map((member) => ({
        staffId: String(member.staff_id), displayName: String(member.display_name), teamRole: String(member.team_role),
      })),
    }));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

async function createDueTaskNotifications(staffId: string) {
  await pool.query(
    `WITH eligible AS (
       SELECT t.id AS task_id,recipient.staff_id AS recipient_id,
              CASE WHEN t.due_at::timestamptz < now()
                   THEN 'deadline_overdue' ELSE 'deadline_approaching' END AS notice_type
         FROM smh.staff_tasks t
         CROSS JOIN LATERAL (
           SELECT t.assigned_staff_id AS staff_id WHERE t.assigned_staff_id IS NOT NULL
           UNION
           SELECT m.staff_id FROM smh.staff_team_members m
            WHERE m.team_id=t.team_id AND m.team_role='worker'
              AND t.assigned_staff_id IS NULL
         ) recipient
        WHERE recipient.staff_id=$1 AND t.due_at IS NOT NULL
          AND t.status NOT IN ('approved','cancelled')
          AND t.due_at::timestamptz <= now() + interval '24 hours'
     )
     INSERT INTO smh.staff_task_notifications
       (id,recipient_id,task_id,notification_type,dedupe_key,created)
     SELECT md5(random()::text||clock_timestamp()::text),recipient_id,task_id,notice_type,
            'deadline:'||task_id||':'||recipient_id||':'||current_date::text||':'||notice_type,
            clock_timestamp()::text
       FROM eligible
     ON CONFLICT(dedupe_key) DO NOTHING`,
    [staffId],
  );
}

router.get("/portal/task-notifications", async (req, res): Promise<void> => {
  await createDueTaskNotifications(req.portalIdentity!.id);
  const result = await pool.query(
    `SELECT id,task_id,notification_type,created,read_at
       FROM smh.staff_task_notifications WHERE recipient_id=$1
      ORDER BY read_at NULLS FIRST,created DESC LIMIT 50`,
    [req.portalIdentity!.id],
  );
  res.json(ListStaffTaskNotificationsResponse.parse({
    notifications: result.rows.map((row) => ({
      notificationId: String(row.id),
      taskId: String(row.task_id),
      type: String(row.notification_type),
      created: String(row.created),
      readAt: row.read_at == null ? null : String(row.read_at),
    })),
  }));
});

router.patch("/portal/task-notifications/:notificationId/read", requireSameOrigin, async (req, res): Promise<void> => {
  const params = MarkStaffTaskNotificationReadParams.safeParse(req.params);
  if (!params.success) {
    res.status(404).json({ error: "Notification not found." });
    return;
  }
  const result = await pool.query(
    `UPDATE smh.staff_task_notifications SET read_at=COALESCE(read_at,$1)
      WHERE id=$2 AND recipient_id=$3
      RETURNING id,task_id,notification_type,created,read_at`,
    [new Date().toISOString(), params.data.notificationId, req.portalIdentity!.id],
  );
  const row = result.rows[0];
  if (!row) {
    res.status(404).json({ error: "Notification not found." });
    return;
  }
  res.json(MarkStaffTaskNotificationReadResponse.parse({
    notificationId: String(row.id),
    taskId: String(row.task_id),
    type: String(row.notification_type),
    created: String(row.created),
    readAt: row.read_at == null ? null : String(row.read_at),
  }));
});

router.get("/portal/report-notifications", async (req, res): Promise<void> => {
  const result = await pool.query(
    `SELECT n.*,r.period,r.period_start
       FROM smh.staff_report_notifications n
       JOIN smh.staff_activity_reports r ON r.id=n.report_id
      WHERE n.recipient_id=$1
      ORDER BY n.read_at NULLS FIRST,n.created DESC LIMIT 50`,
    [req.portalIdentity!.id],
  );
  res.json(ListStaffReportNotificationsResponse.parse({
    notifications: result.rows.map(publicReportNotification),
  }));
});

router.patch("/portal/report-notifications/:notificationId/read", requireSameOrigin, async (req, res): Promise<void> => {
  const params = MarkStaffReportNotificationReadParams.safeParse(req.params);
  if (!params.success) {
    res.status(404).json({ error: "Report notification not found." });
    return;
  }
  const result = await pool.query(
    `WITH updated AS (
       UPDATE smh.staff_report_notifications
          SET read_at=COALESCE(read_at,$1)
        WHERE id=$2 AND recipient_id=$3
        RETURNING *
     )
     SELECT updated.*,r.period,r.period_start
       FROM updated JOIN smh.staff_activity_reports r ON r.id=updated.report_id`,
    [new Date().toISOString(),params.data.notificationId,req.portalIdentity!.id],
  );
  if (!result.rows[0]) {
    res.status(404).json({ error: "Report notification not found." });
    return;
  }
  res.json(MarkStaffReportNotificationReadResponse.parse(publicReportNotification(result.rows[0])));
});

router.get("/portal/dashboard", async (req, res): Promise<void> => {
  const assignedOnly = req.portalIdentity!.role === "agent" ? req.portalIdentity!.id : null;
  const counts = await pool.query(
    `SELECT
       count(*) FILTER (WHERE status IN ('open','reply_sending'))::int AS open_count,
       count(*) FILTER (WHERE status='reply_uncertain')::int AS uncertain_count,
       count(*) FILTER (WHERE status='replied')::int AS replied_count,
       count(*) FILTER (WHERE status='closed')::int AS closed_count
      FROM ${supportSchema}.assistant_escalations
     WHERE ($1::text IS NULL OR assigned_staff_id=$1)`,
    [assignedOnly],
  );
  const recent = await pool.query(
    `SELECT id,user_id,question,status,workflow_status,category,priority,assigned_staff_id,created,updated
        FROM ${supportSchema}.assistant_escalations
       WHERE ($1::text IS NULL OR assigned_staff_id=$1)
      ORDER BY updated DESC
      LIMIT 8`,
    [assignedOnly],
  );
  const row = counts.rows[0] ?? {};
  res.json(GetPortalDashboardResponse.parse({
    openCount: Number(row.open_count ?? 0),
    uncertainCount: Number(row.uncertain_count ?? 0),
    repliedCount: Number(row.replied_count ?? 0),
    closedCount: Number(row.closed_count ?? 0),
    recentCases: recent.rows.map(publicCase),
  }));
});

router.get("/portal/command-center", async (req, res): Promise<void> => {
  if (!canViewOwnerCommandCenter(req.portalIdentity!.role)) {
    res.status(403).json({ error: "Only the owner can view the command center." });
    return;
  }
  if (!isDevelopmentCommandCenterAvailable(process.env.NODE_ENV, supportSchema)) {
    res.status(404).json({ error: "This Development-only dashboard is not available here." });
    return;
  }

  const snapshot = await readDevelopmentCommandCenter(
    async (sql, values) => {
      const result = await pool.query(sql, values);
      return { rows: result.rows };
    },
  );
  res.json(GetPortalCommandCenterResponse.parse(snapshot));
});

router.get("/portal/channel-history", async (req, res): Promise<void> => {
  if (!canViewOwnerCommandCenter(req.portalIdentity!.role)) {
    res.status(403).json({ error: "Only the owner can view channel history." });
    return;
  }
  if (!isDevelopmentCommandCenterAvailable(process.env.NODE_ENV, supportSchema)) {
    res.status(404).json({ error: "Development channel history is not available here." });
    return;
  }
  const parsed = GetPortalChannelHistoryQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Choose a valid history page and destination." });
    return;
  }
  try {
    const snapshot = await readDevelopmentChannelHistory(
      async (sql, values) => {
        const result = await pool.query(sql, values);
        return { rows: result.rows };
      },
      parsed.data,
    );
    res.json(GetPortalChannelHistoryResponse.parse(snapshot));
  } catch (error) {
    if (error && typeof error === "object" && "code" in error && error.code === "42P01") {
      res.status(503).json({ error: "Development channel-history migration is not applied yet." });
      return;
    }
    throw error;
  }
});

function tradeManagementIsUnavailable(req: Request, res: Response): boolean {
  if (!canViewOwnerCommandCenter(req.portalIdentity!.role)) {
    res.status(403).json({ error: "Only the owner can manage trades." });
    return true;
  }
  if (!isTradeManagementAvailable(process.env.NODE_ENV, supportSchema)) {
    res.status(404).json({ error: "Trade management is available only in the matching Production or isolated Development portal." });
    return true;
  }
  return false;
}

function signalControlsAreUnavailable(req: Request, res: Response): boolean {
  if (req.portalIdentity?.role !== "owner") {
    res.status(403).json({ error: "Only the owner can manage signal controls." });
    return true;
  }
  if (!isPortalSignalControlAvailable(process.env.NODE_ENV, supportSchema)) {
    res.status(404).json({ error: "Signal controls are available only in isolated Development." });
    return true;
  }
  return false;
}

async function readTradeWorkerSnapshot() {
  const result = await pool.query(
    `SELECT value FROM ${supportSchema}.kv WHERE key='portal_trade_worker_status' LIMIT 1`,
  );
  return workerSnapshot(result.rows[0]?.value);
}

function commandResponse(row: Record<string, unknown>) {
  return CreatePortalTradeActionResponse.parse(publicTradeAction(row));
}

function databaseUnavailable(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "code" in error &&
    ["42P01", "3F000"].includes(String(error.code)));
}

router.get("/portal/trades", async (req, res): Promise<void> => {
  if (tradeManagementIsUnavailable(req, res)) return;
  try {
    const snapshot = await readPortalTrades(
      async (sql, values) => {
        const result = await pool.query(sql, values);
        return { rows: result.rows };
      },
      supportSchema,
      process.env.NODE_ENV,
    );
    res.json(ListPortalTradesResponse.parse(snapshot));
  } catch (error) {
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Trade storage is not available in this environment yet." });
      return;
    }
    throw error;
  }
});

router.get("/portal/signals", async (req, res): Promise<void> => {
  if (signalControlsAreUnavailable(req, res)) return;
  try {
    const panel = await readPortalSignalPanel(
      async (sql, values) => {
        const result = await pool.query(sql, values);
        return { rows: result.rows };
      },
      supportSchema,
      process.env.NODE_ENV,
    );
    res.json(GetPortalSignalControlResponse.parse(panel));
  } catch (error) {
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Signal controls need the Development database migration and isolated test bot." });
      return;
    }
    throw error;
  }
});

router.post("/portal/signals/actions", requireSameOrigin, async (req, res): Promise<void> => {
  if (signalControlsAreUnavailable(req, res)) return;
  const parsed = CreatePortalSignalActionBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Complete the signal action fields and try again." });
    return;
  }
  let normalizedInput: Record<string, unknown>;
  try {
    normalizedInput = normalizePortalSignalInput(
      parsed.data.action as SignalAction,
      parsed.data.input as Record<string, unknown>,
    );
  } catch (error) {
    res.status(400).json({ error: error instanceof Error ? error.message : "Check the signal action fields." });
    return;
  }
  const inputJson = JSON.stringify(normalizedInput);
  const workerResult = await pool.query(
    `SELECT value FROM ${supportSchema}.kv WHERE key=$1 LIMIT 1`,
    ["portal_signal_worker_status"],
  );
  const worker = signalWorkerSnapshot(workerResult.rows[0]?.value);
  if (worker.workerStatus !== "ready") {
    res.status(503).json({
      error: worker.workerStatus === "migration_required"
        ? "The Development signal-controls migration is required before the bot can process this action."
        : "The isolated test bot is not connected to the Support Portal yet.",
    });
    return;
  }

  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const existing = await client.query(
      `SELECT * FROM ${supportSchema}.portal_signal_commands WHERE request_id=$1 FOR UPDATE`,
      [parsed.data.requestId],
    );
    if (existing.rows[0]) {
      const row = existing.rows[0] as Record<string, unknown>;
      const sameRequest = String(row.actor_staff_id) === req.portalIdentity!.id
        && String(row.action) === parsed.data.action
        && String(row.input_json) === inputJson;
      await client.query("ROLLBACK");
      if (!sameRequest) {
        res.status(409).json({ error: "That request reference was already used for a different action." });
        return;
      }
      res.status(200).json(CreatePortalSignalActionResponse.parse(publicSignalCommand(row)));
      return;
    }
    const commandId = randomUUID().replaceAll("-", "");
    const stamp = new Date().toISOString();
    const inserted = await client.query(
      `INSERT INTO ${supportSchema}.portal_signal_commands
         (id,actor_staff_id,action,input_json,request_id,command_status,created,updated)
       VALUES($1,$2,$3,$4,$5,'queued',$6,$6)
       ON CONFLICT(request_id) DO NOTHING RETURNING *`,
      [commandId, req.portalIdentity!.id, parsed.data.action, inputJson, parsed.data.requestId, stamp],
    );
    let row = inserted.rows[0] as Record<string, unknown> | undefined;
    let statusCode = 201;
    if (!row) {
      const duplicate = await client.query(
        `SELECT * FROM ${supportSchema}.portal_signal_commands WHERE request_id=$1`,
        [parsed.data.requestId],
      );
      row = duplicate.rows[0] as Record<string, unknown> | undefined;
      statusCode = 200;
      if (!row || String(row.actor_staff_id) !== req.portalIdentity!.id ||
          String(row.action) !== parsed.data.action || String(row.input_json) !== inputJson) {
        await client.query("ROLLBACK");
        res.status(409).json({ error: "That request reference was already used for a different action." });
        return;
      }
    } else {
      await client.query(
        `INSERT INTO ${supportSchema}.portal_signal_command_events
           (id,command_id,actor_staff_id,event_type,detail,created)
         VALUES($1,$2,$3,'queued','Owner queued a Development signal-control action.',$4)`,
        [randomUUID().replaceAll("-", ""), commandId, req.portalIdentity!.id, stamp],
      );
    }
    await client.query("COMMIT");
    res.status(statusCode).json(CreatePortalSignalActionResponse.parse(publicSignalCommand(row)));
  } catch (error) {
    await client.query("ROLLBACK");
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Signal-control storage is not migrated in this Development database." });
      return;
    }
    throw error;
  } finally {
    client.release();
  }
});

router.get("/portal/signal-actions/:commandId", async (req, res): Promise<void> => {
  if (signalControlsAreUnavailable(req, res)) return;
  const params = GetPortalSignalActionParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Choose a valid signal action." });
    return;
  }
  const result = await pool.query(
    `SELECT * FROM ${supportSchema}.portal_signal_commands WHERE id=$1 LIMIT 1`,
    [params.data.commandId],
  );
  const row = result.rows[0] as Record<string, unknown> | undefined;
  if (!row) {
    res.status(404).json({ error: "Signal action not found." });
    return;
  }
  res.json(GetPortalSignalActionResponse.parse(publicSignalCommand(row)));
});

router.post("/portal/signal-actions/:commandId/confirm", requireSameOrigin, async (req, res): Promise<void> => {
  if (signalControlsAreUnavailable(req, res)) return;
  const params = ConfirmPortalSignalActionParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Choose a valid signal action." });
    return;
  }
  const workerResult = await pool.query(
    `SELECT value FROM ${supportSchema}.kv WHERE key=$1 LIMIT 1`,
    ["portal_signal_worker_status"],
  );
  const worker = signalWorkerSnapshot(workerResult.rows[0]?.value);
  if (worker.workerStatus !== "ready" || !worker.publishingEnabled || !worker.destinationsVerified) {
    res.status(409).json({ error: "Publishing is locked or the private test destinations have not been verified." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const changed = await client.query(
      `UPDATE ${supportSchema}.portal_signal_commands
          SET command_status='approved',updated=$1
        WHERE id=$2 AND command_status='preview_ready'
        RETURNING *`,
      [new Date().toISOString(), params.data.commandId],
    );
    let row = changed.rows[0] as Record<string, unknown> | undefined;
    if (!row) {
      const existing = await client.query(
        `SELECT * FROM ${supportSchema}.portal_signal_commands WHERE id=$1 LIMIT 1`,
        [params.data.commandId],
      );
      row = existing.rows[0] as Record<string, unknown> | undefined;
      if (!row) {
        await client.query("ROLLBACK");
        res.status(404).json({ error: "Signal action not found." });
        return;
      }
      if (row.command_status === "approved" || row.command_status === "completed") {
        await client.query("COMMIT");
        res.json(ConfirmPortalSignalActionResponse.parse(publicSignalCommand(row)));
        return;
      }
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This action is no longer waiting for confirmation." });
      return;
    }
    await client.query(
      `INSERT INTO ${supportSchema}.portal_signal_command_events
         (id,command_id,actor_staff_id,event_type,detail,created)
       VALUES($1,$2,$3,'approved','Owner confirmed the reviewed Development preview.',$4)`,
      [randomUUID().replaceAll("-", ""), params.data.commandId, req.portalIdentity!.id, new Date().toISOString()],
    );
    await client.query("COMMIT");
    res.json(ConfirmPortalSignalActionResponse.parse(publicSignalCommand(row)));
  } catch (error) {
    await client.query("ROLLBACK");
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Signal-control storage is not available in Development." });
      return;
    }
    throw error;
  } finally {
    client.release();
  }
});

router.post("/portal/signal-actions/:commandId/cancel", requireSameOrigin, async (req, res): Promise<void> => {
  if (signalControlsAreUnavailable(req, res)) return;
  const params = CancelPortalSignalActionParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Choose a valid signal action." });
    return;
  }
  const stamp = new Date().toISOString();
  const result = await pool.query(
    `UPDATE ${supportSchema}.portal_signal_commands
        SET command_status='cancelled',safe_result='Draft cancelled. Nothing was sent.',updated=$1,completed_at=$1
      WHERE id=$2 AND command_status IN ('queued','preview_ready')
      RETURNING *`,
    [stamp, params.data.commandId],
  );
  const row = result.rows[0] as Record<string, unknown> | undefined;
  if (row) {
    await pool.query(
      `INSERT INTO ${supportSchema}.portal_signal_command_events
         (id,command_id,actor_staff_id,event_type,detail,created)
       VALUES($1,$2,$3,'cancelled','Owner cancelled an unsent signal action.',$4)`,
      [randomUUID().replaceAll("-", ""), params.data.commandId, req.portalIdentity!.id, stamp],
    );
    res.json(CancelPortalSignalActionResponse.parse(publicSignalCommand(row)));
    return;
  }
  const existing = await pool.query(
    `SELECT * FROM ${supportSchema}.portal_signal_commands WHERE id=$1 LIMIT 1`,
    [params.data.commandId],
  );
  const current = existing.rows[0] as Record<string, unknown> | undefined;
  if (!current) {
    res.status(404).json({ error: "Signal action not found." });
    return;
  }
  if (current.command_status === "cancelled") {
    res.json(CancelPortalSignalActionResponse.parse(publicSignalCommand(current)));
    return;
  }
  res.status(409).json({ error: "This action has already been approved or completed." });
});

router.get("/portal/trades/:tradeId", async (req, res): Promise<void> => {
  if (tradeManagementIsUnavailable(req, res)) return;
  const params = GetPortalTradeParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Choose a valid trade." });
    return;
  }
  try {
    const detail = await readPortalTrade(
      async (sql, values) => {
        const result = await pool.query(sql, values);
        return { rows: result.rows };
      },
      supportSchema,
      process.env.NODE_ENV,
      params.data.tradeId,
    );
    if (!detail) {
      res.status(404).json({ error: "Trade not found." });
      return;
    }
    res.json(GetPortalTradeResponse.parse(detail));
  } catch (error) {
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Trade storage is not available in this environment yet." });
      return;
    }
    throw error;
  }
});

router.post("/portal/trades/:tradeId/actions", requireSameOrigin, async (req, res): Promise<void> => {
  if (tradeManagementIsUnavailable(req, res)) return;
  const params = CreatePortalTradeActionParams.safeParse(req.params);
  const parsed = CreatePortalTradeActionBody.safeParse(req.body);
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Complete the trade action fields and try again." });
    return;
  }

  let normalizedInput: Record<string, unknown>;
  try {
    normalizedInput = normalizeTradeActionInput(
      parsed.data.action as TradeAction,
      parsed.data.input as TradeActionValues,
    );
  } catch (error) {
    res.status(400).json({ error: error instanceof Error ? error.message : "Check the trade action fields." });
    return;
  }

  const inputJson = JSON.stringify(normalizedInput);
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const existing = await client.query(
      `SELECT * FROM ${supportSchema}.portal_trade_commands WHERE request_id=$1 FOR UPDATE`,
      [parsed.data.requestId],
    );
    if (existing.rows[0]) {
      const row = existing.rows[0] as Record<string, unknown>;
      const sameRequest = String(row.actor_staff_id) === req.portalIdentity!.id &&
        String(row.trade_id) === params.data.tradeId &&
        String(row.action) === parsed.data.action &&
        String(row.input_json) === inputJson;
      await client.query("ROLLBACK");
      if (!sameRequest) {
        res.status(409).json({ error: "That request reference was already used for a different trade action." });
        return;
      }
      res.status(200).json(commandResponse(row));
      return;
    }

    const tradeResult = await client.query(
      `SELECT id,data,state,version FROM ${supportSchema}.trades WHERE id=$1 FOR UPDATE`,
      [params.data.tradeId],
    );
    const tradeRow = tradeResult.rows[0] as Record<string, unknown> | undefined;
    if (!tradeRow) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "Trade not found." });
      return;
    }
    const tradeData = typeof tradeRow.data === "string"
      ? JSON.parse(String(tradeRow.data)) as Record<string, unknown>
      : tradeRow.data as Record<string, unknown>;
    const state = String(tradeRow.state);
    const hasEntry = tradeData.entry != null && String(tradeData.entry).trim() !== "";
    if (!["ACTIVE", "CONFIRMED_BUY", "CONFIRMED_SELL"].includes(state)) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This trade is closed and cannot receive another update." });
      return;
    }
    if (parsed.data.action === "cancel" && hasEntry) {
      await client.query("ROLLBACK");
      res.status(400).json({ error: "This trade has an entry. Choose Invalidate Trade instead." });
      return;
    }
    if (parsed.data.action === "invalidate" && !hasEntry) {
      await client.query("ROLLBACK");
      res.status(400).json({ error: "This setup has no recorded entry. Choose Cancel Setup instead." });
      return;
    }
    if (!tradeData.message_id && !tradeData.setup_message_id) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This trade has no linked Telegram post, so it cannot be safely updated." });
      return;
    }
    const workerResult = await client.query(
      `SELECT value FROM ${supportSchema}.kv WHERE key='portal_trade_worker_status' LIMIT 1`,
    );
    const worker = workerSnapshot(workerResult.rows[0]?.value);
    if (worker.workerStatus !== "ready") {
      await client.query("ROLLBACK");
      res.status(503).json({
        error: worker.workerStatus === "migration_required"
          ? "Trade-management database migration is required before the bot can process this draft."
          : "The matching bot is not connected to the portal yet.",
      });
      return;
    }

    const commandId = randomUUID();
    const created = new Date().toISOString();
    const inserted = await client.query(
      `INSERT INTO ${supportSchema}.portal_trade_commands
         (id,trade_id,actor_staff_id,action,input_json,expected_version,request_id,command_status,created,updated)
       VALUES($1,$2,$3,$4,$5,$6,$7,'queued',$8,$8)
       ON CONFLICT(request_id) DO NOTHING
       RETURNING *`,
      [commandId, params.data.tradeId, req.portalIdentity!.id, parsed.data.action,
       inputJson, Number(tradeRow.version), parsed.data.requestId, created],
    );
    let commandRow = inserted.rows[0] as Record<string, unknown> | undefined;
    let statusCode = 201;
    if (!commandRow) {
      const duplicate = await client.query(
        `SELECT * FROM ${supportSchema}.portal_trade_commands WHERE request_id=$1`,
        [parsed.data.requestId],
      );
      commandRow = duplicate.rows[0] as Record<string, unknown> | undefined;
      statusCode = 200;
      if (!commandRow || String(commandRow.actor_staff_id) !== req.portalIdentity!.id ||
          String(commandRow.trade_id) !== params.data.tradeId ||
          String(commandRow.action) !== parsed.data.action ||
          String(commandRow.input_json) !== inputJson) {
        await client.query("ROLLBACK");
        res.status(409).json({ error: "That request reference was already used for a different trade action." });
        return;
      }
    } else {
      await client.query(
        `INSERT INTO ${supportSchema}.portal_trade_command_events
           (id,command_id,actor_staff_id,event_type,detail,created)
         VALUES($1,$2,$3,'queued','Draft created by the portal owner.',$4)`,
        [randomUUID(), commandRow.id, req.portalIdentity!.id, created],
      );
    }
    await client.query("COMMIT");
    res.status(statusCode).json(commandResponse(commandRow));
  } catch (error) {
    await client.query("ROLLBACK");
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Trade-management storage is not migrated in this environment yet." });
      return;
    }
    throw error;
  } finally {
    client.release();
  }
});

router.get("/portal/trade-actions/:commandId", async (req, res): Promise<void> => {
  if (tradeManagementIsUnavailable(req, res)) return;
  const params = GetPortalTradeActionParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Choose a valid trade action." });
    return;
  }
  try {
    const result = await pool.query(
      `SELECT * FROM ${supportSchema}.portal_trade_commands WHERE id=$1 LIMIT 1`,
      [params.data.commandId],
    );
    const row = result.rows[0] as Record<string, unknown> | undefined;
    if (!row) {
      res.status(404).json({ error: "Trade action not found." });
      return;
    }
    res.json(GetPortalTradeActionResponse.parse(publicTradeAction(row)));
  } catch (error) {
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Trade-management storage is not migrated in this environment yet." });
      return;
    }
    throw error;
  }
});

router.post("/portal/trade-actions/:commandId/confirm", requireSameOrigin, async (req, res): Promise<void> => {
  if (tradeManagementIsUnavailable(req, res)) return;
  const params = ConfirmPortalTradeActionParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Choose a valid trade action." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await client.query(
      `SELECT * FROM ${supportSchema}.portal_trade_commands WHERE id=$1 FOR UPDATE`,
      [params.data.commandId],
    );
    const row = result.rows[0] as Record<string, unknown> | undefined;
    if (!row) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "Trade action not found." });
      return;
    }
    if (["approved", "completed", "uncertain"].includes(String(row.command_status))) {
      await client.query("ROLLBACK");
      res.json(ConfirmPortalTradeActionResponse.parse(publicTradeAction(row)));
      return;
    }
    if (row.command_status !== "preview_ready") {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This action is not ready for confirmation. Review its current status." });
      return;
    }
    const updatedTime = new Date(String(row.updated)).getTime();
    if (!Number.isFinite(updatedTime) || Date.now() - updatedTime > 5 * 60_000) {
      await client.query(
        `UPDATE ${supportSchema}.portal_trade_commands SET command_status='stale',safe_result=$1,updated=$2,completed_at=$2
          WHERE id=$3 AND command_status='preview_ready'`,
        ["This preview expired. Review the current trade and create a new preview.", new Date().toISOString(), params.data.commandId],
      );
      await client.query("COMMIT");
      res.status(409).json({ error: "This preview expired. Open the trade and prepare a fresh review." });
      return;
    }
    const workerResult = await client.query(
      `SELECT value FROM ${supportSchema}.kv WHERE key='portal_trade_worker_status' LIMIT 1`,
    );
    const worker = workerSnapshot(workerResult.rows[0]?.value);
    if (worker.workerStatus !== "ready" || !worker.publishingEnabled || !worker.destinationsVerified) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "Publishing is locked or the bot destination has not been verified. Nothing was sent." });
      return;
    }
    const changed = await client.query(
      `UPDATE ${supportSchema}.portal_trade_commands SET command_status='approved',updated=$1
        WHERE id=$2 AND command_status='preview_ready' RETURNING *`,
      [new Date().toISOString(), params.data.commandId],
    );
    const updatedRow = changed.rows[0] as Record<string, unknown> | undefined;
    if (!updatedRow) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This action has already changed state. Refresh before continuing." });
      return;
    }
    await client.query(
      `INSERT INTO ${supportSchema}.portal_trade_command_events
         (id,command_id,actor_staff_id,event_type,detail,created)
       VALUES($1,$2,$3,'approved','Owner confirmed the reviewed preview.',$4)`,
      [randomUUID(), params.data.commandId, req.portalIdentity!.id, new Date().toISOString()],
    );
    await client.query("COMMIT");
    res.json(ConfirmPortalTradeActionResponse.parse(publicTradeAction(updatedRow)));
  } catch (error) {
    await client.query("ROLLBACK");
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Trade-management storage is not migrated in this environment yet." });
      return;
    }
    throw error;
  } finally {
    client.release();
  }
});

router.post("/portal/trade-actions/:commandId/cancel", requireSameOrigin, async (req, res): Promise<void> => {
  if (tradeManagementIsUnavailable(req, res)) return;
  const params = CancelPortalTradeActionParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Choose a valid trade action." });
    return;
  }
  try {
    const result = await pool.query(
      `UPDATE ${supportSchema}.portal_trade_commands SET command_status='cancelled',safe_result=$1,
              updated=$2,completed_at=$2
        WHERE id=$3 AND command_status IN ('queued','preview_ready') RETURNING *`,
      ["Draft cancelled. Nothing was sent.", new Date().toISOString(), params.data.commandId],
    );
    if (result.rows[0]) {
      await pool.query(
        `INSERT INTO ${supportSchema}.portal_trade_command_events
           (id,command_id,actor_staff_id,event_type,detail,created)
         VALUES($1,$2,$3,'cancelled','Unsent trade action draft cancelled.',$4)`,
        [randomUUID(), params.data.commandId, req.portalIdentity!.id, new Date().toISOString()],
      );
      res.json(CancelPortalTradeActionResponse.parse(publicTradeAction(result.rows[0] as Record<string, unknown>)));
      return;
    }
    const existing = await pool.query(
      `SELECT * FROM ${supportSchema}.portal_trade_commands WHERE id=$1 LIMIT 1`,
      [params.data.commandId],
    );
    const row = existing.rows[0] as Record<string, unknown> | undefined;
    if (!row) {
      res.status(404).json({ error: "Trade action not found." });
      return;
    }
    if (row.command_status === "cancelled") {
      res.json(CancelPortalTradeActionResponse.parse(publicTradeAction(row)));
      return;
    }
    res.status(409).json({ error: "This action is already being processed or has been sent; check its status." });
  } catch (error) {
    if (databaseUnavailable(error)) {
      res.status(503).json({ error: "Trade-management storage is not migrated in this environment yet." });
      return;
    }
    throw error;
  }
});

function proReviewAvailable(req: Request): boolean {
  return canManageProReviews(req.portalIdentity?.role, process.env.NODE_ENV, supportSchema);
}

function denyProReviewAccess(req: Request, res: Response): boolean {
  if (req.portalIdentity?.role !== "owner") {
    res.status(403).json({ error: "Only the owner can review PRO applications." });
    return true;
  }
  if (!proReviewAvailable(req)) {
    res.status(404).json({ error: "PRO review is available only in the isolated Development environment." });
    return true;
  }
  return false;
}

async function proReviewWorkerIsReady(): Promise<boolean> {
  try {
    const result = await pool.query(
      `SELECT value FROM ${supportSchema}.kv WHERE key='portal_pro_review_worker_status' LIMIT 1`,
    );
    return isProReviewWorkerReady(result.rows[0]?.value);
  } catch {
    return false;
  }
}

router.get("/portal/pro-applications", async (req, res): Promise<void> => {
  if (denyProReviewAccess(req, res)) return;
  const parsed = ListProMemberApplicationsQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Check the application filter and try again." });
    return;
  }
  const status = parsed.data.status ?? "needs_review";
  const limit = parsed.data.limit ?? 50;
  const filters: Record<string, string> = {
    needs_review: "r.status IN ('pending_review','legacy_review') OR r.registration_status='pending_review' OR r.funding_status='pending_review'",
    evidence_requested: "r.funding_status='evidence_requested' OR r.status='information_requested'",
    approved: "r.status='approved'",
    rejected: "r.status='rejected'",
    not_yet_eligible: "r.status='not_yet_eligible'",
    all: "TRUE",
  };
  const proSignalsChannelId = process.env.PRO_SIGNALS_CHANNEL_ID?.trim() ?? "";
  const result = await pool.query(
    `SELECT r.id,r.user_id,r.username,r.status,r.registration_status,r.funding_status,r.source,
            r.evidence_file_id,r.evidence_kind,r.evidence_submitted_at,r.created,r.updated,
            (SELECT a.status FROM ${supportSchema}.access a
              WHERE a.user_id=r.user_id AND a.channel=$2 LIMIT 1) AS channel_access_status
       FROM ${supportSchema}.member_requests r
      WHERE r.destination='pro' AND (${filters[status]})
      ORDER BY r.updated DESC,r.created DESC
      LIMIT $1`,
    [limit, proSignalsChannelId],
  );
  res.json(ListProMemberApplicationsResponse.parse({
    applications: result.rows.map(publicProApplication),
  }));
});

router.get("/portal/pro-applications/:requestId", async (req, res): Promise<void> => {
  if (denyProReviewAccess(req, res)) return;
  const params = GetProMemberApplicationParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Check the application and try again." });
    return;
  }
  const proSignalsChannelId = process.env.PRO_SIGNALS_CHANNEL_ID?.trim() ?? "";
  const applicationResult = await pool.query(
    `SELECT r.id,r.user_id,r.username,r.status,r.registration_status,r.funding_status,r.source,
            r.evidence_file_id,r.evidence_kind,r.evidence_submitted_at,r.created,r.updated,
            (SELECT a.status FROM ${supportSchema}.access a
              WHERE a.user_id=r.user_id AND a.channel=$2 LIMIT 1) AS channel_access_status
       FROM ${supportSchema}.member_requests r
      WHERE r.id=$1 AND r.destination='pro'
      LIMIT 1`,
    [params.data.requestId, proSignalsChannelId],
  );
  const row = applicationResult.rows[0];
  if (!row) {
    res.status(404).json({ error: "That PRO application could not be found." });
    return;
  }
  const [botEvents, commands] = await Promise.all([
    pool.query(
      `SELECT id AS event_id,actor,action,created
         FROM ${supportSchema}.member_request_events
        WHERE request_id=$1
        ORDER BY created DESC
        LIMIT 50`,
      [params.data.requestId],
    ),
    pool.query(
      `SELECT c.*,u.display_name
         FROM ${supportSchema}.portal_member_review_commands c
         LEFT JOIN ${supportSchema}.portal_users u ON u.id=c.actor_id
        WHERE c.request_id=$1
        ORDER BY c.created DESC
        LIMIT 50`,
      [params.data.requestId],
    ),
  ]);
  const history = [
    ...botEvents.rows.map((event) => safeProReviewEvent(event, String(row.user_id))),
    ...commands.rows.map((command) => ({
      eventId: String(command.id),
      action: String(command.action),
      actor: String(command.display_name ?? "Owner"),
      reason: String(command.reason),
      status: String(command.command_status),
      deliveryStatus: String(command.delivery_status),
      created: String(command.created),
      completedAt: command.completed_at == null ? null : String(command.completed_at),
    })),
  ].sort((a, b) => b.created.localeCompare(a.created));
  res.json(GetProMemberApplicationResponse.parse({
    application: publicProApplication(row),
    history,
    latestCommand: commands.rows[0] ? safeProReviewCommand(commands.rows[0]) : null,
  }));
});

router.get("/portal/pro-applications/:requestId/evidence", async (req, res): Promise<void> => {
  if (denyProReviewAccess(req, res)) return;
  const params = GetProMemberApplicationParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Check the application and try again." });
    return;
  }
  const token = process.env.SMH_TEST_TELEGRAM_BOT_TOKEN;
  if (!token) {
    res.status(503).json({ error: "Private evidence viewing is not configured for this test environment." });
    return;
  }
  const result = await pool.query(
    `SELECT evidence_file_id,evidence_kind
       FROM ${supportSchema}.member_requests
      WHERE id=$1 AND destination='pro'
      LIMIT 1`,
    [params.data.requestId],
  );
  const evidence = result.rows[0];
  if (!evidence?.evidence_file_id || !evidence.evidence_kind) {
    res.status(404).json({ error: "No funding evidence is available for this application." });
    return;
  }
  await pool.query(
    `INSERT INTO ${supportSchema}.portal_audit(id,actor_id,action,entity_id,created,detail)
     VALUES($1,$2,'pro_evidence_viewed',$3,$4,'Owner viewed private PRO funding evidence.')`,
    [randomUUID(), req.portalIdentity!.id, params.data.requestId, new Date().toISOString()],
  );
  const file = await downloadTelegramEvidence(
    token,
    String(evidence.evidence_file_id),
    String(evidence.evidence_kind),
  );
  if (!file) {
    req.log.warn({ requestId: params.data.requestId }, "Private PRO evidence could not be retrieved");
    res.status(503).json({ error: "The private evidence could not be loaded. Try again later." });
    return;
  }
  const extension = file.contentType === "application/pdf" ? "pdf"
    : file.contentType === "image/png" ? "png"
      : file.contentType === "image/webp" ? "webp" : "jpg";
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  res.setHeader("Content-Disposition", `inline; filename="private-funding-evidence.${extension}"`);
  res.type(file.contentType).status(200).send(Buffer.from(file.body));
});

router.post("/portal/pro-applications/:requestId/decisions", requireSameOrigin, async (req, res): Promise<void> => {
  if (denyProReviewAccess(req, res)) return;
  const params = SubmitProMemberReviewDecisionParams.safeParse(req.params);
  const parsed = SubmitProMemberReviewDecisionBody.safeParse(req.body);
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Enter a review note and confirm the current application before continuing." });
    return;
  }
  const reason = parsed.data.reason.trim();
  if (!reason || secretLike.test(reason)) {
    res.status(400).json({ error: "Enter a review note without passwords, OTPs, or other credentials." });
    return;
  }
  if (!await proReviewWorkerIsReady()) {
    res.status(503).json({
      error: "The isolated test bot review worker is not ready. No decision was queued.",
    });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const existingByKey = await client.query(
      `SELECT * FROM ${supportSchema}.portal_member_review_commands WHERE idempotency_key=$1 LIMIT 1`,
      [parsed.data.idempotencyKey],
    );
    if (existingByKey.rows[0]) {
      const existing = existingByKey.rows[0];
      if (existing.actor_id !== req.portalIdentity!.id ||
          existing.request_id !== params.data.requestId) {
        await client.query("ROLLBACK");
        res.status(409).json({ error: "This action has already been submitted." });
        return;
      }
      await client.query("COMMIT");
      res.status(202).json(SubmitProMemberReviewDecisionResponse.parse(safeProReviewCommand(existing)));
      return;
    }
    const applicationResult = await client.query(
      `SELECT id,user_id,status,registration_status,funding_status,evidence_file_id,updated
         FROM ${supportSchema}.member_requests
        WHERE id=$1 AND destination='pro'
        FOR UPDATE`,
      [params.data.requestId],
    );
    const application = applicationResult.rows[0];
    if (!application) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "That PRO application could not be found." });
      return;
    }
    if (String(application.updated) !== parsed.data.expectedUpdated) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This application changed. Reload it before making a decision." });
      return;
    }
    if (!mayQueueProReviewAction({
      ...application,
      has_evidence: Boolean(application.evidence_file_id),
    }, parsed.data.action)) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "That decision is not available for the application's current status." });
      return;
    }
    const openCommand = await client.query(
      `SELECT id,command_status
         FROM ${supportSchema}.portal_member_review_commands
        WHERE request_id=$1 AND command_status IN ('queued','processing','uncertain')
        LIMIT 1`,
      [params.data.requestId],
    );
    if (openCommand.rows[0]) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "A previous decision is still processing or needs manual review." });
      return;
    }
    const stamp = new Date().toISOString();
    const commandId = randomUUID();
    const inserted = await client.query(
      `INSERT INTO ${supportSchema}.portal_member_review_commands
        (id,request_id,actor_id,action,previous_status,previous_funding_status,expected_updated,
         reason,idempotency_key,command_status,created,updated)
       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,'queued',$10,$10)
       ON CONFLICT DO NOTHING
       RETURNING *`,
      [commandId, params.data.requestId, req.portalIdentity!.id, parsed.data.action,
        application.status, application.funding_status, String(application.updated),
        reason, parsed.data.idempotencyKey, stamp],
    );
    if (!inserted.rows[0]) {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "A duplicate or conflicting review action is already recorded." });
      return;
    }
    await client.query(
      `INSERT INTO ${supportSchema}.portal_audit(id,actor_id,action,entity_id,created,detail)
       VALUES($1,$2,$3,$4,$5,$6)`,
      [randomUUID(), req.portalIdentity!.id, `pro_review_${parsed.data.action}`,
        params.data.requestId, stamp, reason],
    );
    await client.query("COMMIT");
    res.status(202).json(
      SubmitProMemberReviewDecisionResponse.parse(safeProReviewCommand(inserted.rows[0])),
    );
  } catch (error) {
    await client.query("ROLLBACK");
    const errorCode = error && typeof error === "object" && "code" in error
      ? String((error as { code?: unknown }).code) : "";
    if (errorCode === "23505") {
      res.status(409).json({ error: "A duplicate or conflicting review action is already recorded." });
      return;
    }
    throw error;
  } finally {
    client.release();
  }
});

router.get("/portal/cases", async (req, res): Promise<void> => {
  const parsed = ListPortalCasesQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Check the case filters and try again." });
    return;
  }
  const status = parsed.data.status ?? "open";
  const limit = parsed.data.limit ?? 50;
  const search = parsed.data.search?.trim() ?? "";
  const assignedOnly = req.portalIdentity!.role === "agent" ? req.portalIdentity!.id : null;
  const result = await pool.query(
    `SELECT id,user_id,question,status,workflow_status,category,priority,assigned_staff_id,created,updated
        FROM ${supportSchema}.assistant_escalations
      WHERE ($1='all' OR status=$1)
        AND ($2='' OR question ILIKE $3)
        AND ($4::text IS NULL OR assigned_staff_id=$4)
      ORDER BY updated DESC
      LIMIT $5`,
    [status, search, `%${search}%`, assignedOnly, limit],
  );
  const count = await pool.query(
    `SELECT count(*)::int AS total
        FROM ${supportSchema}.assistant_escalations
      WHERE ($1='all' OR status=$1)
        AND ($2='' OR question ILIKE $3)
        AND ($4::text IS NULL OR assigned_staff_id=$4)`,
    [status, search, `%${search}%`, assignedOnly],
  );
  res.json(ListPortalCasesResponse.parse({
    cases: result.rows.map(publicCase),
    total: Number(count.rows[0]?.total ?? 0),
  }));
});

router.get("/portal/cases/:caseId", async (req, res): Promise<void> => {
  const params = GetPortalCaseParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "That support request could not be found." });
    return;
  }
  const assignedOnly = req.portalIdentity!.role === "agent" ? req.portalIdentity!.id : null;
  const result = await pool.query(
    `SELECT id,user_id,question,status,workflow_status,category,priority,assigned_staff_id,created,updated
        FROM ${supportSchema}.assistant_escalations
       WHERE id=$1 AND ($2::text IS NULL OR assigned_staff_id=$2)`,
    [params.data.caseId, assignedOnly],
  );
  const row = result.rows[0];
  if (!row) {
    res.status(404).json({ error: "That support request could not be found." });
    return;
  }
  const replies = await pool.query(
    `SELECT id,case_id,responder_name,text,status,created,updated
       FROM ${supportSchema}.assistant_support_replies
      WHERE case_id=$1 ORDER BY created ASC`,
    [params.data.caseId],
  );
  const notes = await pool.query(
    `SELECT id,staff_id,responder_name,note,created
       FROM ${supportSchema}.assistant_case_notes WHERE case_id=$1 ORDER BY created ASC`,
    [params.data.caseId],
  );
  const events = await pool.query(
    `SELECT e.id,e.event_type,e.old_value,e.new_value,e.created,
            COALESCE(u.display_name,'Staff') AS actor_name
       FROM ${supportSchema}.assistant_case_events e
       LEFT JOIN ${supportSchema}.portal_users u ON u.id=e.actor_id
      WHERE e.case_id=$1 ORDER BY e.created ASC`,
    [params.data.caseId],
  );
  res.json(GetPortalCaseResponse.parse({
    ...publicCase(row),
    replies: replies.rows.map(publicReply),
    notes: notes.rows.map(publicNote),
    events: events.rows.map(publicCaseEvent),
  }));
});

router.post("/portal/cases/:caseId/replies", requireSameOrigin, async (req, res): Promise<void> => {
  const params = CreatePortalCaseReplyParams.safeParse(req.params);
  const parsed = CreatePortalCaseReplyBody.safeParse(req.body);
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Check the reply and try again." });
    return;
  }
  const text = parsed.data.text.trim();
  if (text.length < 3 || text.length > 3000 || secretLike.test(text)) {
    res.status(400).json({ error: "Remove credentials or provide a reply between 3 and 3,000 characters." });
    return;
  }
  const identity = req.portalIdentity!;
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const caseResult = await client.query(
      `SELECT id,user_id,question,status,created,updated,assigned_staff_id
         FROM ${supportSchema}.assistant_escalations
        WHERE id=$1 AND ($2::text IS NULL OR assigned_staff_id=$2) FOR UPDATE`,
      [params.data.caseId, req.portalIdentity!.role === "agent" ? identity.id : null],
    );
    const supportCase = caseResult.rows[0];
    if (!supportCase) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "That support request could not be found." });
      return;
    }
    const previous = await client.query(
      `SELECT id,case_id,responder_name,text,status,created,updated
         FROM ${supportSchema}.assistant_support_replies
        WHERE case_id=$1 AND request_id=$2`,
      [params.data.caseId, parsed.data.requestId],
    );
    if (previous.rows[0]) {
      await client.query("COMMIT");
      res.status(202).json(CreatePortalCaseReplyResponse.parse(publicReply(previous.rows[0])));
      return;
    }
    if (supportCase.status !== "open") {
      await client.query("ROLLBACK");
      res.status(409).json({ error: "This request is not open for a new reply." });
      return;
    }
    if (supportSchema !== "smh") {
      const mirroredStaff = await client.query(
        `INSERT INTO ${supportSchema}.portal_users
           (id,email,display_name,password_hash,role,active,must_change_password,created,updated,last_login)
         SELECT id,'support-' || id || '@test.invalid',display_name,'disabled-test-mirror',
                role,active,FALSE,created,updated,last_login
           FROM smh.portal_users WHERE id=$1 AND active=TRUE
         ON CONFLICT(id) DO UPDATE SET
           display_name=EXCLUDED.display_name,role=EXCLUDED.role,
           active=EXCLUDED.active,updated=EXCLUDED.updated
         RETURNING id`,
        [identity.id],
      );
      if (!mirroredStaff.rows[0]) {
        await client.query("ROLLBACK");
        res.status(403).json({ error: "Your staff account is inactive. Sign in again." });
        return;
      }
    }
    const replyId = randomUUID();
    const created = new Date().toISOString();
    const replyResult = await client.query(
      `INSERT INTO ${supportSchema}.assistant_support_replies
         (id,case_id,staff_id,responder_name,text,status,request_id,created,updated)
       VALUES($1,$2,$3,$4,$5,'queued',$6,$7,$7)
       RETURNING id,case_id,responder_name,text,status,created,updated`,
      [replyId, params.data.caseId, identity.id, identity.displayName, text, parsed.data.requestId, created],
    );
    await client.query(
      `UPDATE ${supportSchema}.assistant_escalations SET status='reply_sending',updated=$1
        WHERE id=$2 AND status='open'`,
      [created, params.data.caseId],
    );
    await insertAudit(client, identity.id, "reply_queued", params.data.caseId, replyId);
    await client.query("COMMIT");
    res.status(202).json(CreatePortalCaseReplyResponse.parse(publicReply(replyResult.rows[0])));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.post("/portal/cases/:caseId/close", requireSameOrigin, async (req, res): Promise<void> => {
  const params = ClosePortalCaseParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "That support request could not be found." });
    return;
  }
  const identity = req.portalIdentity!;
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await client.query(
      `UPDATE ${supportSchema}.assistant_escalations
          SET status='closed',workflow_status='closed',updated=$1
        WHERE id=$2 AND status IN ('open','replied')
          AND ($3::text IS NULL OR assigned_staff_id=$3)
        RETURNING id,user_id,question,status,workflow_status,category,priority,assigned_staff_id,created,updated`,
      [new Date().toISOString(), params.data.caseId,
       identity.role === "agent" ? identity.id : null],
    );
    if (!result.rows[0]) {
      const exists = await client.query(
        `SELECT id FROM ${supportSchema}.assistant_escalations
          WHERE id=$1 AND ($2::text IS NULL OR assigned_staff_id=$2)`,
        [params.data.caseId, identity.role === "agent" ? identity.id : null],
      );
      await client.query("ROLLBACK");
      res.status(exists.rows[0] ? 409 : 404).json({
        error: exists.rows[0]
          ? "Resolve the reply status before closing this request."
          : "That support request could not be found.",
      });
      return;
    }
    await insertAudit(client, identity.id, "case_closed", params.data.caseId);
    await client.query("COMMIT");
    res.json(ClosePortalCaseResponse.parse(publicCase(result.rows[0])));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.patch("/portal/cases/:caseId/assignment", requireSameOrigin, async (req, res): Promise<void> => {
  const params = AssignPortalCaseParams.safeParse(req.params);
  const parsed = AssignPortalCaseBody.safeParse(req.body);
  const identity = req.portalIdentity!;
  if (!canManageCases(identity.role)) {
    res.status(403).json({ error: "Only an owner or support manager can assign cases." });
    return;
  }
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Choose a valid staff member or leave the case unassigned." });
    return;
  }
  const assignedStaffId = parsed.data.assignedStaffId;
  if (assignedStaffId) {
    const activeStaff = await pool.query(
      "SELECT id FROM smh.portal_users WHERE id=$1 AND active=TRUE",
      [assignedStaffId],
    );
    if (!activeStaff.rows[0]) {
      res.status(400).json({ error: "That staff account is inactive or unavailable." });
      return;
    }
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const current = await client.query(
      `SELECT id,user_id,question,status,created,updated,assigned_staff_id,workflow_status,category,priority
         FROM ${supportSchema}.assistant_escalations WHERE id=$1 FOR UPDATE`,
      [params.data.caseId],
    );
    const row = current.rows[0];
    if (!row) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "That support request could not be found." });
      return;
    }
    const oldAssignee = row.assigned_staff_id == null ? null : String(row.assigned_staff_id);
    await client.query(
      `UPDATE ${supportSchema}.assistant_escalations
          SET assigned_staff_id=$1,workflow_status=$2,updated=$3 WHERE id=$4`,
      [assignedStaffId, assignedStaffId ? "assigned" : "new", new Date().toISOString(), params.data.caseId],
    );
    await client.query(
      `INSERT INTO ${supportSchema}.assistant_case_events
         (id,case_id,actor_id,event_type,old_value,new_value,created)
       VALUES($1,$2,$3,$4,$5,$6,$7)`,
      [randomUUID(), params.data.caseId, identity.id, assignedStaffId ? "assigned" : "unassigned",
       oldAssignee ?? "", assignedStaffId ?? "", new Date().toISOString()],
    );
    await insertAudit(client, identity.id, assignedStaffId ? "case_assigned" : "case_unassigned", params.data.caseId);
    await client.query("COMMIT");
    res.json(AssignPortalCaseResponse.parse({
      ...publicCase(row),
      assignedStaffId: assignedStaffId ?? null,
      workflowStatus: assignedStaffId ? "assigned" : "new",
      updated: new Date().toISOString(),
    }));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.post("/portal/cases/:caseId/notes", requireSameOrigin, async (req, res): Promise<void> => {
  const params = AddPortalCaseNoteParams.safeParse(req.params);
  const parsed = AddPortalCaseNoteBody.safeParse(req.body);
  const identity = req.portalIdentity!;
  const text = parsed.success ? parsed.data.text.trim() : "";
  if (!params.success || !parsed.success || text.length < 3 || text.length > 3000 || secretLike.test(text)) {
    res.status(400).json({ error: "Enter a private note between 3 and 3,000 characters without credentials." });
    return;
  }
  const assignedOnly = identity.role === "agent" ? identity.id : null;
  const caseResult = await pool.query(
    `SELECT id FROM ${supportSchema}.assistant_escalations
      WHERE id=$1 AND ($2::text IS NULL OR assigned_staff_id=$2)`,
    [params.data.caseId, assignedOnly],
  );
  if (!caseResult.rows[0]) {
    res.status(404).json({ error: "That support request could not be found." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    if (supportSchema !== "smh") {
      await client.query(
        `INSERT INTO ${supportSchema}.portal_users
           (id,email,display_name,password_hash,role,active,must_change_password,created,updated,last_login)
         SELECT id,'support-' || id || '@test.invalid',display_name,'disabled-test-mirror',
                 CASE WHEN role='admin' THEN 'owner' ELSE role END,TRUE,FALSE,$2,$2,NULL
           FROM smh.portal_users WHERE id=$1
         ON CONFLICT(id) DO UPDATE SET display_name=EXCLUDED.display_name,active=TRUE`,
        [identity.id, new Date().toISOString()],
      );
    }
    const created = new Date().toISOString();
    const noteId = randomUUID();
    const result = await client.query(
      `INSERT INTO ${supportSchema}.assistant_case_notes(id,case_id,staff_id,responder_name,note,created)
       VALUES($1,$2,$3,$4,$5,$6) RETURNING id,staff_id,responder_name,note,created`,
      [noteId, params.data.caseId, identity.id, identity.displayName, text, created],
    );
    await insertAudit(client, identity.id, "case_note_added", params.data.caseId, noteId);
    await client.query("COMMIT");
    res.status(201).json(AddPortalCaseNoteResponse.parse(publicNote(result.rows[0])));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.get("/portal/staff", async (req, res): Promise<void> => {
  if (!req.portalIdentity || !canManageCases(req.portalIdentity.role)) {
    res.status(403).json({ error: "Case-management permission is required." });
    return;
  }
  const result = await pool.query(
    `SELECT u.id,u.email,u.display_name,u.role,u.active,u.must_change_password,u.created,u.last_login,
            (u.role='manager' OR mr.staff_id IS NOT NULL) AS is_manager
       FROM smh.portal_users u
       LEFT JOIN smh.portal_manager_roles mr ON mr.staff_id=u.id
      ORDER BY u.role,u.email`,
  );
  res.json(ListPortalStaffResponse.parse({ staff: result.rows.map(publicStaff) }));
});

router.post("/portal/staff", requireSameOrigin, async (req, res): Promise<void> => {
  if (!req.portalIdentity || !canManageStaff(req.portalIdentity.role)) {
    res.status(403).json({ error: "Administrator permission is required." });
    return;
  }
  const parsed = CreatePortalStaffBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Enter a valid email address and display name." });
    return;
  }
  const email = parsed.data.email.trim().toLowerCase();
  const displayName = parsed.data.displayName.trim().replace(/\s+/g, " ");
  if (!displayName || displayName.length > 80 || /\p{Cc}/u.test(displayName)) {
    res.status(400).json({ error: "Enter a name between 1 and 80 characters." });
    return;
  }
  const staffId = randomUUID();
  const temporaryPassword = makeTemporaryPassword();
  const created = new Date().toISOString();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const insert = await client.query(
      `INSERT INTO smh.portal_users
         (id,email,display_name,password_hash,role,active,must_change_password,created,updated)
       VALUES($1,$2,$3,$4,'agent',TRUE,TRUE,$5,$5)
       RETURNING id,email,display_name,role,active,must_change_password,created,last_login`,
      [staffId, email, displayName, hashPassword(temporaryPassword), created],
    );
    if (parsed.data.role === "manager") {
      await client.query(
        "INSERT INTO smh.portal_manager_roles(staff_id,created) VALUES($1,$2)",
        [staffId, created],
      );
    }
    await insertAudit(client, req.portalIdentity.id, "staff_created", staffId);
    await client.query("COMMIT");
    res.status(201).json(CreatePortalStaffResponse.parse({
      staff: publicStaff({ ...insert.rows[0], is_manager: parsed.data.role === "manager" }),
      temporaryPassword,
    }));
  } catch (error) {
    await client.query("ROLLBACK");
    if (typeof error === "object" && error !== null && "code" in error && error.code === "23505") {
      res.status(409).json({ error: "An account already exists for that email." });
      return;
    }
    throw error;
  } finally {
    client.release();
  }
});

router.patch("/portal/staff/:staffId", requireSameOrigin, async (req, res): Promise<void> => {
  if (!req.portalIdentity || !canManageStaff(req.portalIdentity.role)) {
    res.status(403).json({ error: "Administrator permission is required." });
    return;
  }
  const params = UpdatePortalStaffParams.safeParse(req.params);
  const parsed = UpdatePortalStaffBody.safeParse(req.body);
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Check the staff account and try again." });
    return;
  }
  if (params.data.staffId === req.portalIdentity.id && !parsed.data.active) {
    res.status(409).json({ error: "You cannot deactivate your own administrator account." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await client.query(
      `UPDATE smh.portal_users
          SET active=$1,updated=$2
        WHERE id=$3 AND role IN ('agent','manager')
        RETURNING id,email,display_name,role,active,must_change_password,created,last_login`,
      [parsed.data.active, new Date().toISOString(), params.data.staffId],
    );
    if (!result.rows[0]) {
      await client.query("ROLLBACK");
      res.status(404).json({ error: "That staff account could not be found." });
      return;
    }
    if (supportSchema !== "smh") {
      await client.query(
        `UPDATE ${supportSchema}.portal_users SET active=$1,updated=$2 WHERE id=$3`,
        [parsed.data.active, new Date().toISOString(), params.data.staffId],
      );
    }
    if (!parsed.data.active) {
      await client.query("DELETE FROM smh.portal_sessions WHERE staff_id=$1", [params.data.staffId]);
      const queued = await client.query(
        `UPDATE ${supportSchema}.assistant_support_replies SET status='failed',updated=$1
          WHERE staff_id=$2 AND status='queued' RETURNING case_id`,
        [new Date().toISOString(), params.data.staffId],
      );
      for (const row of queued.rows) {
        await client.query(
          `UPDATE ${supportSchema}.assistant_escalations SET status='open',updated=$1
            WHERE id=$2 AND status='reply_sending'`,
          [new Date().toISOString(), row.case_id],
        );
      }
    }
    await insertAudit(client, req.portalIdentity.id, parsed.data.active ? "staff_activated" : "staff_deactivated",
      params.data.staffId);
    await client.query("COMMIT");
    res.json(UpdatePortalStaffResponse.parse(publicStaff(result.rows[0])));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.use((error: unknown, req: Request, res: Response, _next: NextFunction): void => {
  const errorType = error instanceof Error ? error.name : "UnknownError";
  req.log.error({ errorType }, "Support portal request failed");
  if (!res.headersSent) {
    res.status(503).json({ error: "The support portal is temporarily unavailable." });
  }
});

export default router;
