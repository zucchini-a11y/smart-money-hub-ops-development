import test from "node:test";
import assert from "node:assert/strict";
import {
  GetPortalChannelHistoryQueryParams,
  GetPortalChannelHistoryResponse,
} from "@workspace/api-zod";
import { readDevelopmentChannelHistory } from "../src/lib/portal-channel-history.ts";
import { canViewOwnerCommandCenter, isDevelopmentCommandCenterAvailable } from "../src/lib/owner-command-center-policy.ts";

test("isolated-test history reads only its schema and returns no technical identifiers", async () => {
  let queryArgs;
  const snapshot = await readDevelopmentChannelHistory(async (sql, values) => {
    queryArgs = { sql, values };
    return { rows: [
      {
        source: "bot",
        destination: "PRO Signals",
        event_type: "signal",
        status: "done",
        recorded_at: "2026-10-21T09:00:00.000Z",
        message_text: "<b>BUY NOW — XAUUSD</b><br>Confirmation received.",
        attachment_label: "Chart image attached",
        operation_id: "internal-operation",
        chat_id: -100123,
        message_id: 987,
      },
      {
        source: "telegram_manual",
        destination: "Market Analysis",
        event_type: "posted",
        status: "received",
        recorded_at: "2026-10-21T08:00:00.000Z",
        message_text: "Educational analysis",
        attachment_label: "Photo attached",
        update_id: 555,
      },
    ] };
  }, { page: 0, limit: 1, destination: "all", bot: "test" });

  assert.match(queryArgs.sql, /^\s*SELECT\b/i);
  assert.ok(queryArgs.sql.includes("smh_test."));
  assert.ok(!queryArgs.sql.includes("smh.operations"));
  assert.deepEqual(queryArgs.values, ["all", 2, 0]);
  assert.equal(snapshot.hasMore, true);
  assert.equal(snapshot.scope, "development_isolated_test");
  assert.equal(snapshot.productionConnected, false);
  assert.equal(snapshot.items.length, 1);
  assert.equal(snapshot.items[0].messageText, "BUY NOW — XAUUSD\nConfirmation received.");
  assert.equal(snapshot.items[0].attachmentLabel, "Chart image attached");
  GetPortalChannelHistoryResponse.parse(snapshot);

  const serialized = JSON.stringify(snapshot);
  for (const hidden of ["internal-operation", "operation_id", "chat_id", "message_id", "update_id", "-100123", "987"]) {
    assert.equal(serialized.includes(hidden), false, `history response must not expose ${hidden}`);
  }
});

test("main-bot Development history reads only the main schema", async () => {
  let queryArgs;
  const snapshot = await readDevelopmentChannelHistory(async (sql, values) => {
    queryArgs = { sql, values };
    return { rows: [] };
  }, {
    page: 0, limit: 25, destination: "all", bot: "main",
  });
  assert.ok(queryArgs.sql.includes("FROM smh.operations"));
  assert.ok(queryArgs.sql.includes("FROM smh.channel_history"));
  assert.ok(!queryArgs.sql.includes("smh_test."));
  assert.deepEqual(queryArgs.values, ["all", 26, 0]);
  assert.equal(snapshot.scope, "development_main_bot");
  assert.equal(snapshot.productionConnected, false);
  assert.equal(snapshot.hasMore, false);
  assert.deepEqual(snapshot.items, []);
  GetPortalChannelHistoryResponse.parse(snapshot);
});

test("empty history returns a valid Development page", async () => {
  const snapshot = await readDevelopmentChannelHistory(async () => ({ rows: [] }), {
    page: 2, limit: 25, destination: "education", bot: "test",
  });
  assert.equal(snapshot.page, 2);
  assert.equal(snapshot.hasMore, false);
  assert.deepEqual(snapshot.items, []);
  GetPortalChannelHistoryResponse.parse(snapshot);
});

test("database failures remain visible to the route instead of becoming fabricated history", async () => {
  await assert.rejects(
    () => readDevelopmentChannelHistory(async () => { throw new Error("missing history migration"); }, {
      page: 0, limit: 25, destination: "all", bot: "main",
    }),
    /missing history migration/,
  );
});

test("history access policy is owner-only and Development isolated-test only", () => {
  assert.equal(canViewOwnerCommandCenter("owner"), true);
  assert.equal(canViewOwnerCommandCenter("manager"), false);
  assert.equal(canViewOwnerCommandCenter("agent"), false);
  assert.equal(isDevelopmentCommandCenterAvailable("development", "smh_test"), true);
  assert.equal(isDevelopmentCommandCenterAvailable("production", "smh"), false);
  assert.equal(isDevelopmentCommandCenterAvailable("development", "smh"), false);
});

test("history source defaults to main and rejects arbitrary schema names", () => {
  assert.equal(GetPortalChannelHistoryQueryParams.parse({}).bot, "main");
  assert.equal(
    GetPortalChannelHistoryQueryParams.safeParse({ bot: "smh_test; DROP SCHEMA smh" }).success,
    false,
  );
});
