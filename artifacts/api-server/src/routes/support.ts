import {
  createHash,
  timingSafeEqual,
  randomUUID,
} from "node:crypto";
import { Router, type IRouter, type Request, type Response } from "express";
import { pool } from "@workspace/db";
import {
  AcknowledgeBotSupportReplyBody,
  AcknowledgeBotSupportReplyParams,
  AcknowledgeBotSupportReplyResponse,
  AddSupportCaseNoteBody,
  AddSupportCaseNoteParams,
  AddSupportCaseNoteResponse,
  AssignSupportCaseBody,
  AssignSupportCaseParams,
  AssignSupportCaseResponse,
  ClaimBotSupportRepliesResponse,
  CreateBotSupportCaseBody,
  CreateBotSupportCaseResponse,
  CreateMemberBotCaseMessageBody,
  CreateMemberBotCaseMessageParams,
  CreateMemberBotCaseMessageResponse,
  CreateSupportReplyBody,
  CreateSupportReplyParams,
  CreateSupportReplyResponse,
  GetMemberBotCaseQueryParams,
  GetMemberBotCaseResponse,
  GetSupportCaseParams,
  GetSupportCaseResponse,
  GetSupportSessionResponse,
  ListMemberBotCasesQueryParams,
  ListMemberBotCasesResponse,
  ListSupportCasesQueryParams,
  ListSupportCasesResponse,
  ListSupportStaffResponse,
  UpdateSupportCaseStatusBody,
  UpdateSupportCaseStatusParams,
  UpdateSupportCaseStatusResponse,
} from "@workspace/api-zod";

const router: IRouter = Router();
const requestedSchema = process.env.SMH_SUPPORT_SCHEMA;
const productionSupportEnabled =
  process.env.NODE_ENV === "production" &&
  process.env.SMH_SUPPORT_PRODUCTION_ENABLED === "true" &&
  requestedSchema === "smh" &&
  Boolean(process.env.SMH_DATABASE_URL);
const developmentSupportEnabled =
  process.env.NODE_ENV !== "production" &&
  process.env.SMH_SUPPORT_PRODUCTION_ENABLED !== "true" &&
  (!requestedSchema || requestedSchema === "smh_test");
const schema: "smh" | "smh_test" = productionSupportEnabled ? "smh" : "smh_test";
const SESSION_COOKIE = "smh_support_session";
const PORTAL_SESSION_COOKIE = "smh_portal_session";
const SECRET_LIKE =
  /\b(password|passcode|otp|one[- ]time code|recovery code|api key|access token|private key)\b/i;

type StaffRole = "owner" | "manager" | "agent";
type StaffIdentity = {
  id: string;
  email: string;
  displayName: string;
  role: StaffRole;
};
type BotIdentity = "signals" | "coach";

function isDevSchemaEnabled(res: Response): boolean {
  if (!productionSupportEnabled && !developmentSupportEnabled) {
    res.status(404).json({ error: "Support API is not enabled in this environment." });
    return false;
  }
  return true;
}

function staffRoleSql(alias: "u"): string {
  if (schema !== "smh") return `${alias}.role`;
  return `CASE
    WHEN ${alias}.role='admin' THEN 'owner'
    WHEN ${alias}.role='agent' AND EXISTS (
      SELECT 1 FROM smh.portal_manager_roles pm WHERE pm.staff_id=${alias}.id
    ) THEN 'manager'
    ELSE ${alias}.role
  END`;
}

function safeText(value: unknown, min: number, max: number): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (text.length < min || text.length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(text)) return null;
  if (SECRET_LIKE.test(text)) return null;
  return text;
}

function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function requestCookie(req: Request, name: string): string | null {
  const cookie = req.headers.cookie?.split(";").map((part) => part.trim()).find((part) => part.startsWith(`${name}=`));
  return cookie ? decodeURIComponent(cookie.slice(name.length + 1)) : null;
}

function clearSessionCookie(res: Response): void {
  res.setHeader("Set-Cookie", `${SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/api/support; Max-Age=0`);
}

function sameOrigin(req: Request): boolean {
  const origin = req.get("origin");
  if (!origin) return process.env.NODE_ENV !== "production";
  try {
    return new URL(origin).host === req.get("host");
  } catch {
    return false;
  }
}

function sessionView(staff: StaffIdentity | null, needsSetup: boolean) {
  return GetSupportSessionResponse.parse({
    authenticated: Boolean(staff),
    needsSetup,
    staff: staff ? { id: staff.id, displayName: staff.displayName, role: staff.role } : null,
  });
}

async function staffIdentity(req: Request): Promise<StaffIdentity | null> {
  for (const cookieName of [PORTAL_SESSION_COOKIE, SESSION_COOKIE]) {
    const token = requestCookie(req, cookieName);
    if (!token || token.length > 200) continue;
    const result = await pool.query(
      `SELECT u.id,u.email,u.display_name,u.must_change_password,${staffRoleSql("u")} AS role
         FROM ${schema}.portal_sessions s
         JOIN ${schema}.portal_users u ON u.id=s.staff_id
        WHERE s.token_hash=$1 AND s.expires>$2 AND u.active=TRUE`,
      [hashToken(token), new Date().toISOString()],
    );
    const row = result.rows[0];
    if (!row || Boolean(row.must_change_password)) continue;
    return {
      id: String(row.id),
      email: String(row.email),
      displayName: String(row.display_name),
      role: row.role as StaffRole,
    };
  }
  return null;
}

async function requireStaff(req: Request, res: Response): Promise<StaffIdentity | null> {
  if (!isDevSchemaEnabled(res)) return null;
  const identity = await staffIdentity(req);
  if (!identity) {
    res.status(401).json({ error: "Sign in to view support cases." });
    return null;
  }
  return identity;
}

function requireSameOrigin(req: Request, res: Response): boolean {
  if (!sameOrigin(req)) {
    res.status(403).json({ error: "Cross-site request blocked." });
    return false;
  }
  return true;
}

async function botIdentity(req: Request, res: Response): Promise<BotIdentity | null> {
  if (!isDevSchemaEnabled(res)) return null;
  const header = req.get("authorization") ?? "";
  if (!header.startsWith("Bearer ")) {
    res.status(401).json({ error: "Bot authentication required." });
    return null;
  }
  const supplied = Buffer.from(header.slice(7));
  const configured: Array<[BotIdentity, string | undefined]> = [
    ["signals", process.env.SMH_SUPPORT_SIGNALS_TOKEN],
    ["coach", process.env.SMH_SUPPORT_COACH_TOKEN],
  ];
  for (const [bot, expectedValue] of configured) {
    if (!expectedValue) continue;
    const expected = Buffer.from(expectedValue);
    if (expected.length === supplied.length && timingSafeEqual(expected, supplied)) return bot;
  }
  res.status(401).json({ error: "Bot authentication failed." });
  return null;
}

function caseSummary(row: Record<string, unknown>) {
  return {
    caseId: String(row.id),
    sourceBot: row.source_bot as BotIdentity,
    memberId: String(row.user_id),
    question: String(row.question),
    status: String(row.status),
    workflowStatus: String(row.workflow_status),
    category: String(row.category),
    priority: String(row.priority),
    assignedStaffId: row.assigned_staff_id == null ? null : String(row.assigned_staff_id),
    created: String(row.created),
    updated: String(row.updated),
  };
}

function botCase(row: Record<string, unknown>) {
  return {
    caseId: String(row.id),
    sourceBot: row.source_bot as BotIdentity,
    telegramUserId: String(row.user_id),
    question: String(row.question),
    status: String(row.status),
    created: String(row.created),
    updated: String(row.updated),
  };
}

async function visibleCase(caseId: string, identity: StaffIdentity) {
  const result = await pool.query(
    `SELECT * FROM ${schema}.assistant_escalations
      WHERE id=$1 AND ($2::text <> 'agent' OR assigned_staff_id=$3)`,
    [caseId, identity.role, identity.id],
  );
  return result.rows[0] as Record<string, unknown> | undefined;
}

function assignedOnly(identity: StaffIdentity): boolean {
  return identity.role === "agent";
}

async function writeAudit(actorId: string, action: string, entityId: string, detail = ""): Promise<void> {
  await pool.query(
    `INSERT INTO ${schema}.portal_audit(id,actor_id,action,entity_id,created,detail)
     VALUES($1,$2,$3,$4,$5,$6)`,
    [randomUUID(), actorId, action, entityId, new Date().toISOString(), detail],
  );
}

router.get("/support/auth/session", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res)) return;
  const count = await pool.query(`SELECT count(*)::int AS count FROM ${schema}.portal_users`);
  const needsSetup = process.env.NODE_ENV !== "production" && Number(count.rows[0]?.count ?? 0) === 0;
  res.json(sessionView(await staffIdentity(req), needsSetup));
});

router.post("/support/auth/bootstrap", (_req, res): void => {
  res.status(404).json({ error: "Staff accounts can only be created by an authorized owner." });
});

router.post("/support/auth/login", (_req, res): void => {
  res.status(404).json({ error: "Use the shared sign-in page at /login." });
});

router.post("/support/auth/logout", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res) || !requireSameOrigin(req, res)) return;
  const token = requestCookie(req, SESSION_COOKIE);
  if (token) await pool.query(`DELETE FROM ${schema}.portal_sessions WHERE token_hash=$1`, [hashToken(token)]);
  clearSessionCookie(res);
  res.status(204).end();
});

router.get("/support/cases", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res)) return;
  const identity = await requireStaff(req, res);
  if (!identity) return;
  const parsed = ListSupportCasesQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid case filter." });
    return;
  }
  const requested = parsed.data.status ?? "open";
  const statusFilter = requested === "all" ? "" : requested === "closed" ? "AND e.status='closed'" : "AND e.status<>'closed'";
  const assignedFilter = assignedOnly(identity) ? "AND e.assigned_staff_id=$1" : "";
  const values = assignedOnly(identity) ? [identity.id] : [];
  const result = await pool.query(
    `SELECT e.* FROM ${schema}.assistant_escalations e
      WHERE TRUE ${statusFilter} ${assignedFilter}
      ORDER BY CASE WHEN e.workflow_status='new' THEN 0 ELSE 1 END,e.updated DESC LIMIT 200`,
    values,
  );
  res.json(ListSupportCasesResponse.parse({ cases: result.rows.map(caseSummary) }));
});

router.get("/support/cases/:caseId", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res)) return;
  const identity = await requireStaff(req, res);
  if (!identity) return;
  const params = GetSupportCaseParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: "Invalid case ID." });
    return;
  }
  const row = await visibleCase(params.data.caseId, identity);
  if (!row) {
    res.status(404).json({ error: "Case not found or not visible." });
    return;
  }
  const [memberMessages, staffReplies, notes, events] = await Promise.all([
    pool.query(
      `SELECT id,'member' AS sender,'Member' AS display_name,text,'received' AS status,created
         FROM ${schema}.assistant_case_messages WHERE case_id=$1`,
      [params.data.caseId],
    ),
    pool.query(
      `SELECT id,'staff' AS sender,responder_name AS display_name,text,status,created
         FROM ${schema}.assistant_support_replies WHERE case_id=$1 AND status IN ('sent','queued','sending','uncertain','failed')`,
      [params.data.caseId],
    ),
    pool.query(
      `SELECT n.id,n.responder_name AS staff_name,n.note AS text,n.created
         FROM ${schema}.assistant_case_notes n WHERE n.case_id=$1 ORDER BY n.created`,
      [params.data.caseId],
    ),
    pool.query(
      `SELECT e.id,COALESCE(u.display_name,'Staff') AS actor_name,e.event_type,e.old_value,e.new_value,e.created
         FROM ${schema}.assistant_case_events e
         LEFT JOIN ${schema}.portal_users u ON u.id=e.actor_id
        WHERE e.case_id=$1 ORDER BY e.created`,
      [params.data.caseId],
    ),
  ]);
  const messages = [...memberMessages.rows, ...staffReplies.rows].sort((a, b) => String(a.created).localeCompare(String(b.created)));
  res.json(GetSupportCaseResponse.parse({
    case: caseSummary(row),
    messages: messages.map((message) => ({
      id: String(message.id), sender: message.sender, displayName: String(message.display_name),
      text: String(message.text), status: String(message.status), created: String(message.created),
    })),
    notes: notes.rows.map((note) => ({ id: String(note.id), staffName: String(note.staff_name), text: String(note.text), created: String(note.created) })),
    events: events.rows.map((event) => ({
      id: String(event.id), actorName: String(event.actor_name), eventType: String(event.event_type),
      oldValue: String(event.old_value), newValue: String(event.new_value), created: String(event.created),
    })),
  }));
});

router.get("/support/staff", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res)) return;
  const identity = await requireStaff(req, res);
  if (!identity) return;
  const result = await pool.query(
    `SELECT u.id,u.display_name,${staffRoleSql("u")} AS role
       FROM ${schema}.portal_users u WHERE u.active=TRUE ORDER BY u.display_name`,
  );
  res.json(ListSupportStaffResponse.parse(result.rows.map((row) => ({
    id: String(row.id), displayName: String(row.display_name), role: row.role,
  }))));
});

router.post("/support/cases/:caseId/replies", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res) || !requireSameOrigin(req, res)) return;
  const identity = await requireStaff(req, res);
  if (!identity) return;
  const params = CreateSupportReplyParams.safeParse(req.params);
  const parsed = CreateSupportReplyBody.safeParse(req.body);
  const text = parsed.success ? safeText(parsed.data.text, 3, 3000) : null;
  if (!params.success || !parsed.success || !text) {
    res.status(400).json({ error: "Reply is invalid or includes sensitive credential-like text." });
    return;
  }
  const row = await visibleCase(params.data.caseId, identity);
  if (!row) {
    res.status(404).json({ error: "Case not found or not visible." });
    return;
  }
  if (row.status === "closed") {
    res.status(409).json({ error: "This case is closed." });
    return;
  }
  const id = randomUUID();
  const now = new Date().toISOString();
  const result = await pool.query(
    `INSERT INTO ${schema}.assistant_support_replies
       (id,case_id,staff_id,responder_name,text,status,request_id,created,updated)
     VALUES($1,$2,$3,$4,$5,'queued',$6,$7,$7)
     ON CONFLICT (case_id,request_id) DO UPDATE SET request_id=EXCLUDED.request_id
     RETURNING id,'staff' AS sender,responder_name AS display_name,text,status,created`,
    [id, params.data.caseId, identity.id, identity.displayName, text, parsed.data.requestId, now],
  );
  const item = result.rows[0];
  if (item.status === "queued") {
    await pool.query(
      `UPDATE ${schema}.assistant_escalations
          SET status='reply_sending',workflow_status='waiting_for_member',updated=$1
        WHERE id=$2 AND status<>'closed'`,
      [now, params.data.caseId],
    );
    await writeAudit(identity.id, "reply_queued", params.data.caseId, String(item.id));
  }
  res.status(item.status === "queued" ? 202 : 200).json(CreateSupportReplyResponse.parse({
    id: String(item.id), sender: "staff", displayName: String(item.display_name),
    text: String(item.text), status: String(item.status), created: String(item.created),
  }));
});

router.patch("/support/cases/:caseId/assignment", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res) || !requireSameOrigin(req, res)) return;
  const identity = await requireStaff(req, res);
  if (!identity) return;
  if (identity.role === "agent") {
    res.status(403).json({ error: "Only owners and managers can assign cases." });
    return;
  }
  const params = AssignSupportCaseParams.safeParse(req.params);
  const parsed = AssignSupportCaseBody.safeParse(req.body);
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Invalid assignment." });
    return;
  }
  const assignedId = parsed.data.assignedStaffId;
  if (assignedId) {
    const active = await pool.query(`SELECT id FROM ${schema}.portal_users WHERE id=$1 AND active=TRUE`, [assignedId]);
    if (!active.rows[0]) {
      res.status(400).json({ error: "Staff account is inactive or unavailable." });
      return;
    }
  }
  const current = await pool.query(`SELECT * FROM ${schema}.assistant_escalations WHERE id=$1`, [params.data.caseId]);
  if (!current.rows[0]) {
    res.status(404).json({ error: "Case not found." });
    return;
  }
  const oldAssignee = current.rows[0].assigned_staff_id == null ? "" : String(current.rows[0].assigned_staff_id);
  const now = new Date().toISOString();
  const workflow = assignedId ? "assigned" : "new";
  const result = await pool.query(
    `UPDATE ${schema}.assistant_escalations SET assigned_staff_id=$1,workflow_status=$2,updated=$3
      WHERE id=$4 RETURNING *`,
    [assignedId, workflow, now, params.data.caseId],
  );
  await pool.query(
    `INSERT INTO ${schema}.assistant_case_events(id,case_id,actor_id,event_type,old_value,new_value,created)
     VALUES($1,$2,$3,$4,$5,$6,$7)`,
    [randomUUID(), params.data.caseId, identity.id, assignedId ? "assigned" : "unassigned", oldAssignee, assignedId ?? "", now],
  );
  await writeAudit(identity.id, assignedId ? "case_assigned" : "case_unassigned", params.data.caseId);
  res.json(AssignSupportCaseResponse.parse(caseSummary(result.rows[0])));
});

router.patch("/support/cases/:caseId/status", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res) || !requireSameOrigin(req, res)) return;
  const identity = await requireStaff(req, res);
  if (!identity) return;
  if (identity.role === "agent") {
    res.status(403).json({ error: "Only owners and managers can change case workflow status." });
    return;
  }
  const params = UpdateSupportCaseStatusParams.safeParse(req.params);
  const parsed = UpdateSupportCaseStatusBody.safeParse(req.body);
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Invalid workflow status." });
    return;
  }
  const current = await pool.query(`SELECT workflow_status FROM ${schema}.assistant_escalations WHERE id=$1`, [params.data.caseId]);
  if (!current.rows[0]) {
    res.status(404).json({ error: "Case not found." });
    return;
  }
  const now = new Date().toISOString();
  const status = parsed.data.workflowStatus;
  const result = await pool.query(
    `UPDATE ${schema}.assistant_escalations
        SET workflow_status=$1,
            status=CASE WHEN $1='closed' THEN 'closed' WHEN status='closed' THEN 'open' ELSE status END,
            updated=$2
      WHERE id=$3 RETURNING *`,
    [status, now, params.data.caseId],
  );
  await pool.query(
    `INSERT INTO ${schema}.assistant_case_events(id,case_id,actor_id,event_type,old_value,new_value,created)
     VALUES($1,$2,$3,'status_changed',$4,$5,$6)`,
    [randomUUID(), params.data.caseId, identity.id, String(current.rows[0].workflow_status), status, now],
  );
  await writeAudit(identity.id, "case_status_changed", params.data.caseId, status);
  res.json(UpdateSupportCaseStatusResponse.parse(caseSummary(result.rows[0])));
});

router.post("/support/cases/:caseId/notes", async (req, res): Promise<void> => {
  if (!isDevSchemaEnabled(res) || !requireSameOrigin(req, res)) return;
  const identity = await requireStaff(req, res);
  if (!identity) return;
  const params = AddSupportCaseNoteParams.safeParse(req.params);
  const parsed = AddSupportCaseNoteBody.safeParse(req.body);
  const text = parsed.success ? safeText(parsed.data.text, 3, 3000) : null;
  if (!params.success || !parsed.success || !text) {
    res.status(400).json({ error: "Private note is invalid or includes credential-like text." });
    return;
  }
  const row = await visibleCase(params.data.caseId, identity);
  if (!row) {
    res.status(404).json({ error: "Case not found or not visible." });
    return;
  }
  const id = randomUUID();
  const created = new Date().toISOString();
  await pool.query(
    `INSERT INTO ${schema}.assistant_case_notes(id,case_id,staff_id,responder_name,note,created)
     VALUES($1,$2,$3,$4,$5,$6)`,
    [id, params.data.caseId, identity.id, identity.displayName, text, created],
  );
  await writeAudit(identity.id, "private_note_added", params.data.caseId);
  res.status(201).json(AddSupportCaseNoteResponse.parse({ id, staffName: identity.displayName, text, created }));
});

router.post("/support/bot/cases", async (req, res): Promise<void> => {
  const bot = await botIdentity(req, res);
  if (!bot) return;
  const parsed = CreateBotSupportCaseBody.safeParse(req.body);
  const question = parsed.success ? safeText(parsed.data.question, 3, 1000) : null;
  if (!parsed.success || !question || !Number.isSafeInteger(parsed.data.telegramUserId)) {
    res.status(400).json({ error: "Case request is invalid or includes credential-like text." });
    return;
  }
  const id = randomUUID();
  const now = new Date().toISOString();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      "SELECT pg_advisory_xact_lock(hashtext($1))",
      [`support-case:${bot}:${parsed.data.telegramUserId}`],
    );
    const retried = await client.query(
      `SELECT * FROM ${schema}.assistant_escalations WHERE source_bot=$1 AND request_id=$2`,
      [bot, parsed.data.requestId],
    );
    if (retried.rows[0]) {
      await client.query("COMMIT");
      res.status(200).json(CreateBotSupportCaseResponse.parse(botCase(retried.rows[0])));
      return;
    }
    const active = await client.query(
      `SELECT * FROM ${schema}.assistant_escalations
        WHERE source_bot=$1 AND user_id=$2 AND status IN ('open','reply_sending','reply_uncertain')
        ORDER BY created DESC LIMIT 1 FOR UPDATE`,
      [bot, parsed.data.telegramUserId],
    );
    let caseRow: Record<string, unknown>;
    if (active.rows[0]) {
      caseRow = active.rows[0] as Record<string, unknown>;
      await client.query(
        `INSERT INTO ${schema}.assistant_case_messages
           (id,case_id,sender_type,sender_id,text,request_id,created)
         VALUES($1,$2,'member',$3,$4,$5,$6)
         ON CONFLICT (case_id,sender_type,request_id) DO NOTHING`,
        [randomUUID(), caseRow.id, String(parsed.data.telegramUserId), question, parsed.data.requestId, now],
      );
      await client.query(
        `UPDATE ${schema}.assistant_escalations SET updated=$1,workflow_status='in_progress' WHERE id=$2`,
        [now, caseRow.id],
      );
      const refreshed = await client.query(`SELECT * FROM ${schema}.assistant_escalations WHERE id=$1`, [caseRow.id]);
      caseRow = refreshed.rows[0] as Record<string, unknown>;
    } else {
      const created = await client.query(
        `INSERT INTO ${schema}.assistant_escalations
           (id,user_id,question,status,source_bot,request_id,created,updated)
         VALUES($1,$2,$3,'open',$4,$5,$6,$6) RETURNING *`,
        [id, parsed.data.telegramUserId, question, bot, parsed.data.requestId, now],
      );
      caseRow = created.rows[0] as Record<string, unknown>;
    }
    await client.query("COMMIT");
    res.status(201).json(CreateBotSupportCaseResponse.parse(botCase(caseRow)));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.get("/support/bot/cases", async (req, res): Promise<void> => {
  const bot = await botIdentity(req, res);
  if (!bot) return;
  const parsed = ListMemberBotCasesQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid Telegram user ID." });
    return;
  }
  const result = await pool.query(
    `SELECT * FROM ${schema}.assistant_escalations
      WHERE source_bot=$1 AND user_id=$2 ORDER BY created DESC LIMIT 50`,
    [bot, parsed.data.telegramUserId],
  );
  res.json(ListMemberBotCasesResponse.parse({ cases: result.rows.map(botCase) }));
});

router.get("/support/bot/case", async (req, res): Promise<void> => {
  const bot = await botIdentity(req, res);
  if (!bot) return;
  const parsed = GetMemberBotCaseQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid case request." });
    return;
  }
  const result = await pool.query(
    `SELECT * FROM ${schema}.assistant_escalations
      WHERE id=$1 AND source_bot=$2 AND user_id=$3`,
    [parsed.data.caseId, bot, parsed.data.telegramUserId],
  );
  const row = result.rows[0];
  if (!row) {
    res.status(404).json({ error: "Case not found or not owned." });
    return;
  }
  const [memberMessages, staffReplies] = await Promise.all([
    pool.query(`SELECT id,'member' AS sender,'You' AS display_name,text,'received' AS status,created
                  FROM ${schema}.assistant_case_messages WHERE case_id=$1`, [row.id]),
    pool.query(`SELECT id,'staff' AS sender,responder_name AS display_name,text,status,created
                  FROM ${schema}.assistant_support_replies WHERE case_id=$1 AND status='sent'`, [row.id]),
  ]);
  const messages = [
    { id: `case-${row.id}`, sender: "member", displayName: "You", text: String(row.question), status: String(row.status), created: String(row.created) },
    ...memberMessages.rows.map((item) => ({ id: String(item.id), sender: item.sender, displayName: item.display_name, text: String(item.text), status: String(item.status), created: String(item.created) })),
    ...staffReplies.rows.map((item) => ({ id: String(item.id), sender: item.sender, displayName: String(item.display_name), text: String(item.text), status: String(item.status), created: String(item.created) })),
  ].sort((a, b) => a.created.localeCompare(b.created));
  res.json(GetMemberBotCaseResponse.parse({ case: botCase(row), messages }));
});

router.post("/support/bot/cases/:caseId/messages", async (req, res): Promise<void> => {
  const bot = await botIdentity(req, res);
  if (!bot) return;
  const params = CreateMemberBotCaseMessageParams.safeParse(req.params);
  const parsed = CreateMemberBotCaseMessageBody.safeParse(req.body);
  const text = parsed.success ? safeText(parsed.data.text, 3, 3000) : null;
  if (!params.success || !parsed.success || !text || !Number.isSafeInteger(parsed.data.telegramUserId)) {
    res.status(400).json({ error: "Message is invalid or includes credential-like text." });
    return;
  }
  const result = await pool.query(
    `SELECT id,status FROM ${schema}.assistant_escalations
      WHERE id=$1 AND source_bot=$2 AND user_id=$3`,
    [params.data.caseId, bot, parsed.data.telegramUserId],
  );
  const row = result.rows[0];
  if (!row) {
    res.status(404).json({ error: "Case not found or not owned." });
    return;
  }
  if (row.status === "closed") {
    res.status(409).json({ error: "This case is closed." });
    return;
  }
  const id = randomUUID();
  const created = new Date().toISOString();
  const saved = await pool.query(
    `INSERT INTO ${schema}.assistant_case_messages(id,case_id,sender_type,sender_id,text,request_id,created)
     VALUES($1,$2,'member',$3,$4,$5,$6)
     ON CONFLICT (case_id,sender_type,request_id) DO UPDATE SET request_id=EXCLUDED.request_id
     RETURNING id,text,created`,
    [id, params.data.caseId, String(parsed.data.telegramUserId), text, parsed.data.requestId, created],
  );
  await pool.query(
    `UPDATE ${schema}.assistant_escalations SET workflow_status='in_progress',updated=$1 WHERE id=$2`,
    [created, params.data.caseId],
  );
  const item = saved.rows[0];
  res.status(201).json(CreateMemberBotCaseMessageResponse.parse({
    id: String(item.id), sender: "member", displayName: "You", text: String(item.text), status: "received", created: String(item.created),
  }));
});

router.post("/support/bot/outbox/claim", async (req, res): Promise<void> => {
  const bot = await botIdentity(req, res);
  if (!bot) return;
  const now = new Date().toISOString();
  const staleAt = new Date(Date.now() - 5 * 60_000).toISOString();
  await pool.query(
    `WITH stale AS (
       UPDATE ${schema}.assistant_support_replies r SET status='uncertain',updated=$1
         FROM ${schema}.assistant_escalations source_case
        WHERE r.case_id=source_case.id AND source_case.source_bot=$3
          AND r.status='sending' AND r.updated < $2
        RETURNING r.case_id
     )
     UPDATE ${schema}.assistant_escalations e
        SET status='reply_uncertain',updated=$1
       FROM stale WHERE e.id=stale.case_id AND e.source_bot=$3`,
    [now, staleAt, bot],
  );
  const result = await pool.query(
    `WITH selected AS (
       SELECT r.id FROM ${schema}.assistant_support_replies r
       JOIN ${schema}.assistant_escalations e ON e.id=r.case_id
       WHERE r.status='queued' AND e.source_bot=$1
       ORDER BY r.created FOR UPDATE OF r SKIP LOCKED LIMIT 10
     )
     UPDATE ${schema}.assistant_support_replies r SET status='sending',updated=$2
       FROM selected s WHERE r.id=s.id
       RETURNING r.id,r.case_id,r.text,r.responder_name`,
    [bot, new Date().toISOString()],
  );
  const replies = await Promise.all(result.rows.map(async (reply) => {
    const item = await pool.query(
      `SELECT user_id FROM ${schema}.assistant_escalations WHERE id=$1 AND source_bot=$2`,
      [reply.case_id, bot],
    );
    return {
      replyId: String(reply.id), caseId: String(reply.case_id), telegramUserId: String(item.rows[0]?.user_id ?? ""),
      text: String(reply.text), responderName: String(reply.responder_name),
    };
  }));
  res.json(ClaimBotSupportRepliesResponse.parse({ replies }));
});

router.post("/support/bot/outbox/:replyId/ack", async (req, res): Promise<void> => {
  const bot = await botIdentity(req, res);
  if (!bot) return;
  const params = AcknowledgeBotSupportReplyParams.safeParse(req.params);
  const parsed = AcknowledgeBotSupportReplyBody.safeParse(req.body);
  if (!params.success || !parsed.success) {
    res.status(400).json({ error: "Invalid delivery acknowledgement." });
    return;
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await client.query(
      `UPDATE ${schema}.assistant_support_replies r SET status=$1,updated=$2
        FROM ${schema}.assistant_escalations e
       WHERE r.id=$3 AND r.case_id=e.id AND e.source_bot=$4 AND r.status='sending'
       RETURNING r.case_id,r.text,r.responder_name`,
      [parsed.data.outcome, new Date().toISOString(), params.data.replyId, bot],
    );
    if (!result.rows[0]) {
      const already = await client.query(
        `SELECT r.status FROM ${schema}.assistant_support_replies r
         JOIN ${schema}.assistant_escalations e ON e.id=r.case_id
         WHERE r.id=$1 AND e.source_bot=$2`,
        [params.data.replyId, bot],
      );
      await client.query("ROLLBACK");
      if (already.rows[0]?.status === parsed.data.outcome) {
        res.json(AcknowledgeBotSupportReplyResponse.parse({ status: parsed.data.outcome }));
        return;
      }
      res.status(404).json({ error: "Reply not found or no longer deliverable." });
      return;
    }
    const reply = result.rows[0];
    const caseStatus = parsed.data.outcome === "sent" ? "replied" : parsed.data.outcome === "uncertain" ? "reply_uncertain" : "open";
    await client.query(
      `UPDATE ${schema}.assistant_escalations SET status=$1,reply=$2,replied_by_name=$3,updated=$4
        WHERE id=$5`,
      [caseStatus, parsed.data.outcome === "sent" ? reply.text : null, reply.responder_name, new Date().toISOString(), reply.case_id],
    );
    await client.query("COMMIT");
    res.json(AcknowledgeBotSupportReplyResponse.parse({ status: parsed.data.outcome }));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

export default router;
