import assert from "node:assert/strict";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { createRequire } from "node:module";
import { test } from "node:test";
import { hashSessionToken } from "../src/lib/portal-crypto.ts";

const requireFromDb = createRequire(new URL("../../../lib/db/package.json", import.meta.url));
const { Pool } = requireFromDb("pg");
const pool = process.env.DATABASE_URL ? new Pool({ connectionString: process.env.DATABASE_URL }) : null;
const enabled = process.env.SMH_WEBSITE_SUPPORT_E2E_DEV === "1";
const apiBase = process.env.SMH_WEBSITE_SUPPORT_E2E_API ?? "http://127.0.0.1:8080/api";
const origin = new URL(apiBase).origin;

test("website support chat enforces Owner, Manager, Agent, and visitor access in Development", {
  skip: !enabled,
}, async () => {
  assert.ok(pool, "Development DATABASE_URL must be available; its value is never printed");
  assert.equal(process.env.NODE_ENV, "development", "E2E must run in Development");
  assert.equal(process.env.PORTAL_SUPPORT_SCHEMA, "smh_test", "E2E must use the isolated support schema");
  const schemaCheck = await pool.query(
    "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name='smh_test') AS found",
  );
  assert.equal(schemaCheck.rows[0]?.found, true, "isolated Development schema must exist");

  const run = randomUUID().replaceAll("-", "");
  const ownerId = `website-chat-owner-${run}`;
  const managerId = `website-chat-manager-${run}`;
  const otherManagerId = `website-chat-other-manager-${run}`;
  const agentId = `website-chat-agent-${run}`;
  const secondAgentId = `website-chat-agent-two-${run}`;
  const outsideAgentId = `website-chat-outside-agent-${run}`;
  const staff = [
    { id: ownerId, role: "admin", name: "Website Chat Test Owner" },
    { id: managerId, role: "manager", name: "Website Chat Test Manager" },
    { id: otherManagerId, role: "manager", name: "Website Chat Other Manager" },
    { id: agentId, role: "agent", name: "Website Chat Test Agent" },
    { id: secondAgentId, role: "agent", name: "Website Chat Second Agent" },
    { id: outsideAgentId, role: "agent", name: "Website Chat Outside Agent" },
  ];
  const teamId = `website-chat-team-${run}`;
  const otherTeamId = `website-chat-other-team-${run}`;
  const firstVisitorToken = `website-chat-visitor-${randomUUID()}-${randomUUID()}`;
  const secondVisitorToken = `website-chat-visitor-${randomUUID()}-${randomUUID()}`;
  const firstVisitorHash = createHash("sha256").update(firstVisitorToken).digest("hex");
  const secondVisitorHash = createHash("sha256").update(secondVisitorToken).digest("hex");
  const firstConversationId = `website-chat-conversation-${run}`;
  const secondConversationId = `website-chat-outside-conversation-${run}`;
  const now = new Date().toISOString();
  const sessionTokens = new Map(staff.map((person) => [person.id, randomBytes(32).toString("base64url")]));
  const cookieFor = (person) => `smh_portal_session=${encodeURIComponent(sessionTokens.get(person.id))}`;
  let previousSettings;
  let seeded = false;

  async function call(path, { method = "GET", cookie, body } = {}) {
    const response = await fetch(`${apiBase}${path}`, {
      method,
      headers: {
        origin,
        ...(body === undefined ? {} : { "content-type": "application/json" }),
        ...(cookie ? { cookie } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch {}
    return {
      status: response.status,
      payload,
      cookie: response.headers.get("set-cookie")?.split(";")[0],
    };
  }

  try {
    const previousSettingsResult = await pool.query(
      "SELECT support_team_id,updated_by,updated FROM smh_test.website_support_settings WHERE singleton=TRUE",
    );
    assert.ok(previousSettingsResult.rows[0], "Development support settings should be initialized");
    previousSettings = previousSettingsResult.rows[0];
    await pool.query("BEGIN");
    for (const person of staff) {
      person.email = `${person.id}@example.invalid`;
      await pool.query(
        `INSERT INTO smh_test.portal_users
           (id,email,display_name,password_hash,role,active,must_change_password,created,updated)
         VALUES($1,$2,$3,$4,$5,TRUE,FALSE,$6,$6)`,
        [person.id, person.email, person.name, "development-e2e-session-only", person.role, now],
      );
    }
    for (const person of staff) {
      const token = sessionTokens.get(person.id);
      await pool.query(
        `INSERT INTO smh_test.portal_sessions(token_hash,staff_id,created,expires)
         VALUES($1,$2,$3,$4)`,
        [hashSessionToken(token), person.id, now, new Date(Date.now() + 60 * 60 * 1000).toISOString()],
      );
    }
    await pool.query(
      `INSERT INTO smh_test.staff_teams(id,name,created_by,created)
       VALUES($1,$2,$3,$4),($5,$6,$3,$4)`,
      [teamId, `Website Chat ${run}`, ownerId, now, otherTeamId, `Website Chat Other ${run}`],
    );
    await pool.query(
      `INSERT INTO smh_test.staff_team_members(team_id,staff_id,team_role,created)
       VALUES($1,$2,'manager',$3),($1,$4,'worker',$3),($1,$5,'worker',$3),
             ($6,$7,'manager',$3),($6,$8,'worker',$3)`,
      [teamId, managerId, now, agentId, secondAgentId, otherTeamId, otherManagerId, outsideAgentId],
    );
    await pool.query(
      `INSERT INTO smh_test.website_support_agent_settings
         (staff_id,female_support_eligible,available,updated)
       VALUES($1,TRUE,TRUE,NOW()),($2,TRUE,TRUE,NOW()),($3,TRUE,TRUE,NOW())`,
      [agentId, secondAgentId, outsideAgentId],
    );
    await pool.query(
      `INSERT INTO smh_test.website_support_visitors(token_hash,expires)
       VALUES($1,NOW()+INTERVAL '1 day'),($2,NOW()+INTERVAL '1 day')`,
      [firstVisitorHash, secondVisitorHash],
    );
    await pool.query(
      `INSERT INTO smh_test.website_support_conversations
         (id,visitor_token_hash,create_request_id,mode,status,visitor_name,team_id)
       VALUES($1,$2,$3,'human','queued','Synthetic visitor',$4),
             ($5,$6,$7,'human','queued','Other synthetic visitor',$8)`,
      [
        firstConversationId, firstVisitorHash, `create-${run}-1`, teamId,
        secondConversationId, secondVisitorHash, `create-${run}-2`, otherTeamId,
      ],
    );
    await pool.query(
      `INSERT INTO smh_test.website_support_messages
         (id,conversation_id,sender_type,display_name,body,request_id)
       VALUES($1,$2,'visitor','Visitor','Development access test message',$3),
             ($4,$5,'visitor','Visitor','Other team access test message',$6)`,
      [
        `message-${run}-1`, firstConversationId, `message-${run}-1`,
        `message-${run}-2`, secondConversationId, `message-${run}-2`,
      ],
    );
    await pool.query(
      `UPDATE smh_test.website_support_settings SET support_team_id=$1 WHERE singleton=TRUE`,
      [teamId],
    );
    await pool.query("COMMIT");
    seeded = true;

    const ownerCookie = cookieFor(staff[0]);
    const managerCookie = cookieFor(staff[1]);
    const otherManagerCookie = cookieFor(staff[2]);
    const agentCookie = cookieFor(staff[3]);
    const secondAgentCookie = cookieFor(staff[4]);
    const outsideAgentCookie = cookieFor(staff[5]);

    const unauthenticated = await call("/portal/website-support/conversations");
    assert.equal(unauthenticated.status, 401);

    const managerSettings = await call("/portal/website-support/settings", { cookie: managerCookie });
    const outsideManagerSettings = await call("/portal/website-support/settings", { cookie: otherManagerCookie });
    assert.equal(managerSettings.payload.canAssign, true);
    assert.ok(managerSettings.payload.agents.some((item) => item.staffId === secondAgentId));
    assert.equal(outsideManagerSettings.payload.canAssign, false);

    const ownerList = await call("/portal/website-support/conversations?status=all", { cookie: ownerCookie });
    const managerList = await call("/portal/website-support/conversations?status=all", { cookie: managerCookie });
    const otherManagerList = await call("/portal/website-support/conversations?status=all", { cookie: otherManagerCookie });
    const agentList = await call("/portal/website-support/conversations?status=all", { cookie: agentCookie });
    const outsideAgentList = await call("/portal/website-support/conversations?status=all", { cookie: outsideAgentCookie });
    assert.ok(ownerList.payload.conversations.some((item) => item.conversationId === firstConversationId));
    assert.ok(managerList.payload.conversations.some((item) => item.conversationId === firstConversationId));
    assert.ok(!otherManagerList.payload.conversations.some((item) => item.conversationId === firstConversationId));
    assert.ok(agentList.payload.conversations.some((item) => item.conversationId === firstConversationId));
    assert.ok(!outsideAgentList.payload.conversations.some((item) => item.conversationId === firstConversationId));

    const wrongTeamDetail = await call(
      `/portal/website-support/conversations/${firstConversationId}`,
      { cookie: otherManagerCookie },
    );
    assert.equal(wrongTeamDetail.status, 404);
    const agentCannotAssign = await call(
      `/portal/website-support/conversations/${firstConversationId}/assignment`,
      { method: "PATCH", cookie: agentCookie, body: { assignedStaffId: secondAgentId } },
    );
    assert.equal(agentCannotAssign.status, 403);

    const accept = await call(
      `/portal/website-support/conversations/${firstConversationId}/accept`,
      { method: "POST", cookie: agentCookie },
    );
    assert.equal(accept.status, 200);
    assert.equal(accept.payload.assignedStaffId, agentId);

    await pool.query(
      `UPDATE smh_test.website_support_agent_settings SET available=FALSE WHERE staff_id=$1`,
      [secondAgentId],
    );
    const unavailableAssignment = await call(
      `/portal/website-support/conversations/${firstConversationId}/assignment`,
      { method: "PATCH", cookie: managerCookie, body: { assignedStaffId: secondAgentId } },
    );
    assert.equal(unavailableAssignment.status, 400);
    await pool.query(
      `UPDATE smh_test.website_support_agent_settings SET available=TRUE WHERE staff_id=$1`,
      [secondAgentId],
    );
    const transfer = await call(
      `/portal/website-support/conversations/${firstConversationId}/assignment`,
      { method: "PATCH", cookie: managerCookie, body: { assignedStaffId: secondAgentId } },
    );
    assert.equal(transfer.status, 200);
    assert.equal(transfer.payload.assignedStaffId, secondAgentId);

    const agentCannotReplyAfterTransfer = await call(
      `/portal/website-support/conversations/${firstConversationId}/replies`,
      {
        method: "POST",
        cookie: agentCookie,
        body: { text: "Not assigned to this chat.", requestId: `reply-${run}-wrong-agent` },
      },
    );
    assert.equal(agentCannotReplyAfterTransfer.status, 404);

    const managerCannotReply = await call(
      `/portal/website-support/conversations/${firstConversationId}/replies`,
      {
        method: "POST",
        cookie: managerCookie,
        body: { text: "Manager replies are not enabled.", requestId: `reply-${run}-manager` },
      },
    );
    assert.equal(managerCannotReply.status, 403);

    const reply = await call(
      `/portal/website-support/conversations/${firstConversationId}/replies`,
      {
        method: "POST",
        cookie: secondAgentCookie,
        body: { text: "A real support agent reply in Development.", requestId: `reply-${run}-agent` },
      },
    );
    assert.equal(reply.status, 201);

    const publicCookie = `smh_web_support_session=${firstVisitorToken}`;
    const visitorDetail = await call(
      `/public-support/conversations/${firstConversationId}`,
      { cookie: publicCookie },
    );
    assert.equal(visitorDetail.status, 200);
    const publicStaffMessage = visitorDetail.payload.messages.find((message) => message.senderType === "staff");
    assert.equal(publicStaffMessage?.displayName, "Support agent");
    assert.notEqual(publicStaffMessage?.displayName, staff[4].name);

    const otherVisitorCannotRead = await call(
      `/public-support/conversations/${firstConversationId}`,
      { cookie: `smh_web_support_session=${secondVisitorToken}` },
    );
    assert.equal(otherVisitorCannotRead.status, 404);

    const crossTeamAssignment = await call(
      `/portal/website-support/conversations/${secondConversationId}/assignment`,
      { method: "PATCH", cookie: managerCookie, body: { assignedStaffId: null } },
    );
    assert.equal(crossTeamAssignment.status, 403);

    const close = await call(
      `/portal/website-support/conversations/${firstConversationId}/close`,
      { method: "POST", cookie: secondAgentCookie },
    );
    assert.equal(close.status, 200);
    const restored = await call("/public-support/conversation", { cookie: publicCookie });
    assert.equal(restored.status, 200);
    assert.equal(restored.payload.conversation, null);
  } finally {
    if (!seeded) await pool.query("ROLLBACK").catch(() => {});
    try {
      await pool.query("BEGIN");
      if (previousSettings) {
        await pool.query(
          `UPDATE smh_test.website_support_settings
              SET support_team_id=$1,updated_by=$2,updated=$3 WHERE singleton=TRUE`,
          [previousSettings.support_team_id, previousSettings.updated_by, previousSettings.updated],
        );
      }
      await pool.query(
        `DELETE FROM smh_test.website_support_conversations WHERE id=ANY($1::text[])`,
        [[firstConversationId, secondConversationId]],
      );
      await pool.query(
        `DELETE FROM smh_test.website_support_visitors WHERE token_hash=ANY($1::text[])`,
        [[firstVisitorHash, secondVisitorHash]],
      );
      await pool.query(
        `DELETE FROM smh_test.portal_audit WHERE actor_id=ANY($1::text[]) OR entity_id=ANY($2::text[])`,
        [staff.map((person) => person.id), [firstConversationId, secondConversationId, "website-support-settings"]],
      );
      await pool.query(
        `DELETE FROM smh_test.website_support_agent_settings WHERE staff_id=ANY($1::text[])`,
        [staff.map((person) => person.id)],
      );
      await pool.query(
        `DELETE FROM smh_test.portal_sessions WHERE staff_id=ANY($1::text[])`,
        [staff.map((person) => person.id)],
      );
      await pool.query(
        `DELETE FROM smh_test.staff_team_members WHERE team_id=ANY($1::text[])`,
        [[teamId, otherTeamId]],
      );
      await pool.query(
        `DELETE FROM smh_test.portal_manager_roles WHERE staff_id=ANY($1::text[])`,
        [staff.map((person) => person.id)],
      );
      await pool.query(
        `DELETE FROM smh_test.staff_teams WHERE id=ANY($1::text[])`,
        [[teamId, otherTeamId]],
      );
      await pool.query(
        `DELETE FROM smh_test.portal_users WHERE id=ANY($1::text[])`,
        [staff.map((person) => person.id)],
      );
      await pool.query("COMMIT");
    } catch {
      await pool.query("ROLLBACK").catch(() => {});
    }
    await pool.end();
  }
});
