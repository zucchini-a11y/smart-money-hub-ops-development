import test from "node:test";
import assert from "node:assert/strict";
import {
  isTradeManagementAvailable,
  normalizeTradeActionInput,
  publicTrade,
  publicTradeAction,
  readPortalTrade,
  readPortalTrades,
  workerSnapshot,
} from "../src/lib/portal-trade-management.ts";

test("environment mapping never crosses Development test data and Production data", () => {
  assert.equal(isTradeManagementAvailable("development", "smh_test"), true);
  assert.equal(isTradeManagementAvailable("production", "smh"), true);
  assert.equal(isTradeManagementAvailable("development", "smh"), false);
  assert.equal(isTradeManagementAvailable("production", "smh_test"), false);
  assert.equal(isTradeManagementAvailable("test", "smh"), false);
});

test("public trade data omits Telegram chat and message identifiers", () => {
  const trade = publicTrade({
    id: "trade-internal-only",
    state: "CONFIRMED_BUY",
    version: 3,
    created: "2026-10-21T10:00:00.000Z",
    updated: "2026-10-21T10:01:00.000Z",
    data: JSON.stringify({
      id: "trade-internal-only",
      symbol: "XAUUSD",
      direction: "BUY",
      entry: "4100.00",
      sl: "4080.00",
      targets: { "1": { price: "4140.00", hit: false } },
      message_id: 991122,
      setup_message_id: 881122,
      chat_id: -100123,
    }),
    event_count: 2,
  });
  assert.equal(trade.symbol, "XAUUSD");
  assert.equal(trade.hasLinkedPost, true);
  assert.equal(trade.targets[0].price, "4140.00");
  assert.equal("message_id" in trade, false);
  assert.equal("chat_id" in trade, false);
  assert.equal(JSON.stringify(trade).includes("991122"), false);
  assert.equal(JSON.stringify(trade).includes("-100123"), false);
});

test("trade list only queries the schema selected by the trusted environment", async () => {
  const statements = [];
  const query = async (sql, values) => {
    statements.push({ sql, values });
    if (sql.includes(".trades")) return { rows: [] };
    return { rows: [{ value: JSON.stringify({
      version: "trade-management-v1",
      status: "ready",
      publishing_enabled: false,
      destinations_verified: false,
      updated: new Date().toISOString(),
    }) }] };
  };
  const result = await readPortalTrades(query, "smh_test", "development");
  assert.equal(result.environment, "development_test");
  assert.equal(result.workerStatus, "ready");
  assert.equal(result.publishingEnabled, false);
  assert.ok(statements.every(({ sql }) => sql.includes("smh_test.")));
  await assert.rejects(() => readPortalTrades(query, "smh", "development"));
});

test("trade detail returns history without message IDs", async () => {
  const query = async (sql) => {
    if (sql.includes("FROM smh_test.trades")) {
      return { rows: [{
        id: "trade-1",
        data: { symbol: "EURUSD", direction: "SELL", message_id: 6677, targets: {} },
        state: "CONFIRMED_SELL",
        version: 2,
        created: "2026-10-21T10:00:00.000Z",
        updated: "2026-10-21T10:01:00.000Z",
        event_count: 1,
      }] };
    }
    return { rows: [{ text: "Stop loss updated.", created: "2026-10-21T10:02:00.000Z", message_id: 7788 }] };
  };
  const detail = await readPortalTrade(query, "smh_test", "development", "trade-1");
  assert.equal(detail.trade.symbol, "EURUSD");
  assert.deepEqual(detail.history[0], {
    text: "Stop loss updated.",
    created: "2026-10-21T10:02:00.000Z",
  });
  assert.equal(JSON.stringify(detail).includes("6677"), false);
  assert.equal(JSON.stringify(detail).includes("7788"), false);
});

test("worker heartbeat is unknown when stale or missing", () => {
  assert.equal(workerSnapshot(null).workerStatus, "unknown");
  assert.equal(workerSnapshot(JSON.stringify({
    status: "ready",
    publishing_enabled: true,
    destinations_verified: true,
    updated: "2020-01-01T00:00:00.000Z",
  })).workerStatus, "unknown");
});

test("action validation requires confirmed trade facts and rejects credential-like text", () => {
  assert.deepEqual(
    normalizeTradeActionInput("partial", { percentage: "25", targetPrice: "4140" }),
    { percentage: "25", target_price: "4140", mode: "reported" },
  );
  assert.throws(
    () => normalizeTradeActionInput("be", { stopMoved: false }),
    /actually moved/,
  );
  assert.throws(
    () => normalizeTradeActionInput("close", { outcome: "Win", outcomeConfirmed: false }),
    /Confirm the recorded outcome/,
  );
  assert.throws(
    () => normalizeTradeActionInput("cancel", { reason: "password: do-not-store" }),
    /Do not enter passwords/,
  );
  assert.throws(
    () => normalizeTradeActionInput("sl", { stopLoss: "98", targetPrice: "110" }),
    /unsupported field/,
  );
});

test("trade action serializer does not expose internal operation or Telegram IDs", () => {
  const value = publicTradeAction({
    id: "command-internal",
    trade_id: "trade-internal",
    action: "sl",
    command_status: "preview_ready",
    preview_text: "Stop loss updated.",
    safe_result: "Preview ready.",
    operation_id: "operation-internal",
    message_id: 1991,
    chat_id: -10042,
    created: "2026-10-21T10:00:00.000Z",
    updated: "2026-10-21T10:00:00.000Z",
  });
  const json = JSON.stringify(value);
  assert.equal(value.canConfirm, true);
  assert.equal(json.includes("operation_id"), false);
  assert.equal(json.includes("1991"), false);
  assert.equal(json.includes("-10042"), false);
});
