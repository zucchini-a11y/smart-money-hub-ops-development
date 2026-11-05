import test from "node:test";
import assert from "node:assert/strict";
import { GetPortalCommandCenterResponse } from "@workspace/api-zod";
import { readDevelopmentCommandCenter } from "../src/lib/portal-command-center.ts";

test("command-center snapshot is assembled from read-only, allowlisted records", async () => {
  const statements = [];
  const fakeQuery = async (sql, values) => {
    statements.push({ sql, values });
    if (sql.includes("assistant_escalations")) {
      return { rows: [{
        open_support_cases: "2",
        uncertain_support_cases: "1",
        overdue_tasks: "3",
        recorded_trades: "4",
        recorded_trade_events: "5",
        unresolved_operations: "1",
         pro_pending_review: "2",
         pro_evidence_requested: "3",
         stale_pro_applications: "1",
      }] };
    }
    if (sql.includes("command_center_health")) {
      return { rows: [{
        value: JSON.stringify({
          checked_at: "2026-10-19T09:59:00.000Z",
          status: "healthy",
          database: "ok",
          telegram: "reachable",
          seconds_since_poll: 4,
          publishing_requested: false,
          token: "must not be returned",
        }),
      }] };
    }
    if (sql.includes("GROUP BY kind,status")) {
      return { rows: [
        { kind: "signal", status: "failed", count: "2", latest_at: "2026-10-19T09:06:00.000Z", id: "never-return-this" },
        { kind: "signal", status: "failed", count: "1", latest_at: "2026-10-19T09:07:00.000Z" },
        { kind: "analysis", status: "uncertain", count: "1", latest_at: "2026-10-19T09:08:00.000Z" },
        { kind: "invite", status: "failed", count: "8", latest_at: "2026-10-19T09:09:00.000Z" },
      ] };
    }
    if (sql.includes(".kv")) return { rows: [{ value: '"2026-10-19T09:00:00.000Z"' }] };
    if (sql.includes(".operations")) {
      return { rows: [
        { kind: "signal", status: "done", created: "2026-10-19T09:01:00.000Z", updated: "2026-10-19T09:02:00.000Z", payload: "must not be returned", id: "internal-op-id" },
        { kind: "analysis", status: "uncertain", created: "2026-10-19T09:03:00.000Z", updated: "2026-10-19T09:04:00.000Z", payload: "private draft text", id: "private-id" },
      ] };
    }
    if (sql.includes(".errors")) {
      return { rows: [{ category: "database_unavailable", count: "2", latest_at: "2026-10-19T09:05:00.000Z", detail: "private error details" }] };
    }
    throw new Error("Unexpected query in command-center test.");
  };

  const snapshot = await readDevelopmentCommandCenter(fakeQuery, "2026-10-19T10:00:00.000Z");
  const validated = GetPortalCommandCenterResponse.parse(snapshot);
  assert.equal(statements.length, 6);
  assert.ok(statements.every(({ sql }) => /^\s*SELECT\b/i.test(sql)));
  assert.ok(statements.every(({ sql }) => sql.includes("smh_test.")));
  assert.ok(statements.every(({ sql }) => !sql.includes("smh.")));
  assert.equal(validated.readOnly, true);
  assert.equal(snapshot.overview.openSupportCases, 2);
  assert.equal(snapshot.overview.unresolvedPublishingOperations, 1);
  assert.equal(snapshot.overview.proPendingReview, 2);
  assert.equal(snapshot.overview.proEvidenceRequested, 3);
  assert.equal(snapshot.overview.staleProApplications, 1);
  assert.equal(snapshot.lastTelegramUpdate, "2026-10-19T09:00:00.000Z");
  const testBot = snapshot.bots.find(({ id }) => id === "isolated_test");
  assert.equal(testBot.healthStatus, "healthy");
  assert.equal(testBot.processStatus, "running");
  assert.equal(testBot.telegramStatus, "healthy");
  assert.equal(testBot.databaseStatus, "healthy");
  assert.equal(testBot.pollingStatus, "healthy");
  assert.equal(testBot.healthCheckedAt, "2026-10-19T09:59:00.000Z");
  assert.equal(testBot.publishingStatus, "disabled");
  assert.equal(snapshot.bots.find(({ id }) => id === "production").workflowStatus, "not_connected");
  assert.equal(snapshot.channels.find(({ sourceBot, name }) => sourceBot === "isolated_test" && name === "PRO Signals").latestRecordedActivity, "2026-10-19T09:02:00.000Z");
  assert.equal(snapshot.recentOperations[0].telegramAccepted, true);
  assert.equal(snapshot.recentOperations[1].destination, "Market Analysis");
  assert.equal(snapshot.recentErrors[0].count, 2);
  assert.equal(snapshot.alerts.length, 3);
  assert.deepEqual(snapshot.alerts.map(({ destination, category, count }) => ({ destination, category, count })), [
    { destination: "Market Analysis", category: "publishing_uncertain", count: 1 },
    { destination: "PRO Signals", category: "publishing_failure", count: 3 },
    { destination: "System", category: "pro_stale_applications", count: 1 },
  ]);

  const serialized = JSON.stringify(snapshot);
  for (const hiddenValue of ["internal-op-id", "private-id", "never-return-this", "private draft text", "private error details", "must not be returned", "payload", "messageId", "channelId", "tradeId"]) {
    assert.equal(serialized.includes(hiddenValue), false, `snapshot must not expose ${hiddenValue}`);
  }
});

test("empty Development storage produces empty lists and zero counts without guessing health", async () => {
  const fakeQuery = async (sql) => {
    if (sql.includes("assistant_escalations")) return { rows: [{}] };
    if (sql.includes("command_center_health")) return { rows: [] };
    if (sql.includes(".kv")) return { rows: [{ value: '"none yet"' }] };
    if (sql.includes(".operations") || sql.includes(".errors")) return { rows: [] };
    throw new Error("Unexpected query in empty-snapshot test.");
  };
  const snapshot = await readDevelopmentCommandCenter(fakeQuery);
  assert.equal(snapshot.overview.openSupportCases, 0);
  assert.equal(snapshot.lastTelegramUpdate, null);
  assert.equal(snapshot.recentOperations.length, 0);
  assert.equal(snapshot.recentErrors.length, 0);
  assert.equal(snapshot.alerts.length, 1);
  assert.equal(snapshot.alerts[0].category, "missing_heartbeat");
  assert.equal(snapshot.alerts[0].latestAt, null);
  assert.ok(snapshot.bots.every(({ healthStatus }) => healthStatus === "unknown"));
  const testBot = snapshot.bots.find(({ id }) => id === "isolated_test");
  assert.equal(testBot.processStatus, "unknown");
  assert.equal(testBot.telegramStatus, "unknown");
});

test("stale or malformed heartbeat does not appear as live health", async () => {
  const fakeQuery = async (sql) => {
    if (sql.includes("assistant_escalations")) return { rows: [{}] };
    if (sql.includes("command_center_health")) return { rows: [{ value: "{invalid" }] };
    if (sql.includes(".kv")) return { rows: [] };
    if (sql.includes(".operations") || sql.includes(".errors")) return { rows: [] };
    throw new Error("Unexpected query in stale-heartbeat test.");
  };
  const staleQuery = async (sql) => {
    const result = await fakeQuery(sql);
    if (sql.includes("command_center_health")) {
      return { rows: [{ value: JSON.stringify({
        checked_at: "2026-10-19T09:55:00.000Z",
        status: "healthy",
        telegram: "reachable",
        database: "ok",
        seconds_since_poll: 4,
        publishing_requested: true,
      }) }] };
    }
    return result;
  };

  const malformed = await readDevelopmentCommandCenter(fakeQuery, "2026-10-19T10:00:00.000Z");
  const stale = await readDevelopmentCommandCenter(staleQuery, "2026-10-19T10:00:00.000Z");
  for (const snapshot of [malformed, stale]) {
    const testBot = snapshot.bots.find(({ id }) => id === "isolated_test");
    assert.equal(testBot.healthStatus, "unknown");
    assert.equal(testBot.processStatus, "unknown");
    assert.equal(testBot.telegramStatus, "unknown");
    assert.equal(testBot.publishingStatus, "unknown");
    assert.equal(testBot.healthCheckedAt, null);
    assert.equal(snapshot.alerts.length, 1);
    assert.equal(snapshot.alerts[0].category, "stale_heartbeat");
  }
});

test("fresh explicit health failures are unhealthy, with one deduplicated alert and no inferred channel state", async () => {
  const fakeQuery = async (sql) => {
    if (sql.includes("assistant_escalations")) return { rows: [{}] };
    if (sql.includes("command_center_health")) return { rows: [{ value: JSON.stringify({
      checked_at: "2026-10-19T09:59:00.000Z",
      status: "unavailable",
      database: "unavailable",
      telegram: "unreachable",
      seconds_since_poll: 400,
      publishing_requested: true,
    }) }] };
    if (sql.includes("GROUP BY kind,status")) return { rows: [] };
    if (sql.includes(".kv")) return { rows: [] };
    if (sql.includes(".operations") || sql.includes(".errors")) return { rows: [] };
    throw new Error("Unexpected query in explicit-health-failure test.");
  };
  const snapshot = await readDevelopmentCommandCenter(fakeQuery, "2026-10-19T10:00:00.000Z");
  const testBot = snapshot.bots.find(({ id }) => id === "isolated_test");
  assert.equal(testBot.healthStatus, "unhealthy");
  assert.equal(testBot.telegramStatus, "offline");
  assert.equal(testBot.databaseStatus, "offline");
  assert.equal(testBot.pollingStatus, "offline");
  assert.equal(testBot.publishingStatus, "enabled");
  assert.equal(snapshot.channels.find(({ sourceBot, name }) => sourceBot === "isolated_test" && name === "PRO Signals").status, "unknown");
  assert.equal(snapshot.alerts.length, 1);
  assert.equal(snapshot.alerts[0].category, "bot_health_failure");
  assert.equal(snapshot.alerts[0].severity, "critical");
});

test("Development query errors are returned to the route instead of being hidden", async () => {
  await assert.rejects(
    () => readDevelopmentCommandCenter(async () => { throw new Error("database unavailable"); }),
    /database unavailable/,
  );
});
