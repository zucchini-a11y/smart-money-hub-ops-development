import assert from "node:assert/strict";
import test from "node:test";
import {
  isPortalSignalControlAvailable,
  normalizePortalSignalInput,
  publicSignalCommand,
  readPortalSignalPanel,
  signalWorkerSnapshot,
} from "../src/lib/portal-signal-control.ts";

test("signal controls are available only for isolated Development storage", () => {
  assert.equal(isPortalSignalControlAvailable("development", "smh_test"), true);
  assert.equal(isPortalSignalControlAvailable("production", "smh_test"), false);
  assert.equal(isPortalSignalControlAvailable("development", "smh"), false);
});

test("zone inputs validate actual values and reject malformed ranges", () => {
  assert.deepEqual(normalizePortalSignalInput("create_zone_draft", {
    market: "XAUUSD",
    low: "4150.00",
    high: "4155",
    timeframe: "M15",
    minutes: 60,
    condition: "M15 bullish candle close",
  }), {
    market: "XAUUSD",
    low: "4150.00",
    high: "4155",
    timeframe: "M15",
    condition: "M15 bullish candle close",
  });
  assert.throws(() => normalizePortalSignalInput("create_zone_draft", {
    market: "XAUUSD", low: "4155", high: "4150", timeframe: "M15", minutes: 60,
  }), /upper zone price must be greater/);
  assert.throws(() => normalizePortalSignalInput("create_zone_draft", {
    market: "XAUUSD", low: "4,150", high: "4155", timeframe: "M15", minutes: 60,
  }), /digits and an optional decimal point/);
  assert.throws(() => normalizePortalSignalInput("create_zone_draft", {
    market: "XAUUSD", low: "4150", high: "4155", timeframe: "M15", minutes: 0,
  }), /1 to 1440 minutes/);
});

test("dynamic text rejects credential-like input and unsupported fields", () => {
  assert.throws(() => normalizePortalSignalInput("publish_analysis", {
    text: "Use password: abc123",
  }), /Do not enter passwords/);
  assert.throws(() => normalizePortalSignalInput("publish_analysis", {
    text: "Educational outlook",
    setupId: "hidden-technical-field",
  }), /unsupported fields/);
  assert.throws(() => normalizePortalSignalInput("create_zone_draft", {
    market: "XAUUSD|SELL", low: "4150", high: "4155", timeframe: "M15", minutes: 60,
  }), /\| character/);
});

test("actions normalize confirmation and signal references without changing their meaning", () => {
  assert.deepEqual(normalizePortalSignalInput("record_confirmation", {
    setupId: "setup-abc", confirmation: "Observed M15 bullish close",
  }), { setup_id: "setup-abc", confirmation: "Observed M15 bullish close" });
  assert.deepEqual(normalizePortalSignalInput("expire_setup", {
    setupId: "setup-abc",
  }), { setup_id: "setup-abc" });
  assert.deepEqual(normalizePortalSignalInput("publish_signal", {
    setupId: "setup-abc", direction: "sell", entryRange: "4151-4154",
    stopLoss: "4160", takeProfits: "4140, 4130",
  }), {
    setup_id: "setup-abc", direction: "SELL", entry_range: "4151-4154",
    stop_loss: "4160", take_profits: "4140, 4130",
  });
  assert.throws(() => normalizePortalSignalInput("publish_signal", {
    setupId: "setup-abc", direction: "BUY",
  }), /entry range/);
  assert.throws(() => normalizePortalSignalInput("publish_signal", {
    setupId: "setup-abc", direction: "HOLD",
  }), /Choose BUY or SELL/);
  assert.deepEqual(normalizePortalSignalInput("publish_zone", {
    draftRevision: "rev-12",
  }), { draft_revision: "rev-12" });
});

test("stale or malformed worker heartbeats are unknown, not falsely healthy", () => {
  assert.equal(signalWorkerSnapshot({
    version: "signal-controls-v1", status: "ready", updated: "not-a-date",
    publishing_enabled: true, destinations_verified: true,
  }).workerStatus, "unknown");
  assert.equal(signalWorkerSnapshot({
    version: "signal-controls-v1", status: "ready", updated: new Date(Date.now() - 120_000).toISOString(),
    publishing_enabled: true, destinations_verified: true,
  }).workerStatus, "unknown");
});

test("panel reader queries only Development test schema and returns separated fields", async () => {
  const calls = [];
  const panel = await readPortalSignalPanel(async (sql, values) => {
    calls.push({ sql, values });
    if (values?.[0] === "portal_signal_panel") {
      return { rows: [{ value: JSON.stringify({
        active_setup: { setup_id: "internal-id", market: "XAUUSD", status: "active", has_chart: true },
        zone_draft: {},
        updated: "now",
      }) }] };
    }
    if (values?.[0] === "portal_signal_worker_status") {
      return { rows: [{ value: JSON.stringify({
        version: "signal-controls-v1",
        status: "ready",
        updated: new Date().toISOString(),
        publishing_enabled: false,
        destinations_verified: false,
      }) }] };
    }
    return { rows: [] };
  }, "smh_test", "development");
  assert.equal(panel.environment, "development_test");
  assert.equal(panel.activeSetup.market, "XAUUSD");
  assert.equal(panel.publishingEnabled, false);
  assert.equal(panel.destinationsVerified, false);
  assert.ok(calls.every((call) => call.sql.includes("smh_test.")));
  await assert.rejects(readPortalSignalPanel(async () => ({ rows: [] }), "smh", "development"));
  await assert.rejects(readPortalSignalPanel(async () => ({ rows: [] }), "smh_test", "production"));
});

test("public action response never exposes operation or actor identifiers", () => {
  const response = publicSignalCommand({
    id: "command-id",
    actor_staff_id: "private-staff-id",
    operation_id: "private-operation-id",
    action: "publish_signal",
    command_status: "preview_ready",
    preview_text: "BUY NOW — XAUUSD",
    safe_result: "",
    created: new Date(0),
    updated: new Date(0),
  });
  assert.equal(response.commandId, "command-id");
  assert.equal("operation_id" in response, false);
  assert.equal("actor_staff_id" in response, false);
});
