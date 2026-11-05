import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import {
  isTestEnvironment,
  missingWorkerSettings,
  resolveWorkspaceRoot,
  shouldStartTelegramWorker,
  startTelegramWorker,
  stopTelegramWorker,
} from "../src/lib/telegram-worker.ts";

const productionEnv = {
  NODE_ENV: "production",
  SMH_ENABLE_TELEGRAM_WORKER: "true",
  TELEGRAM_BOT_TOKEN: "test-token-do-not-log",
  ADMIN_TELEGRAM_ID: "123",
  PRO_SIGNALS_CHANNEL_ID: "-100123",
  MARKET_ANALYSIS_CHANNEL_ID: "-100456",
  DATABASE_URL: "postgres://test.invalid/db",
};

test("worker remains disabled unless explicitly enabled in production", () => {
  assert.equal(shouldStartTelegramWorker({ NODE_ENV: "development", SMH_ENABLE_TELEGRAM_WORKER: "true" }), false);
  assert.equal(shouldStartTelegramWorker({ NODE_ENV: "production", SMH_ENABLE_TELEGRAM_WORKER: "false" }), false);
  assert.equal(shouldStartTelegramWorker({ NODE_ENV: "production" }), false);
  assert.equal(shouldStartTelegramWorker(productionEnv), true);
});

test("test and isolated-test configurations are never eligible for the production worker", () => {
  assert.equal(isTestEnvironment({ SMH_TEST_MODE: "1" }), true);
  assert.equal(isTestEnvironment({ SMH_ISOLATED_TEST_INSTANCE: "true" }), true);
  assert.equal(isTestEnvironment({ SMH_TEST_DATABASE_URL: "sqlite:///test.db" }), true);
  assert.equal(isTestEnvironment({ SMH_TEST_DATABASE_SCHEMA: "smh_test" }), true);
  assert.equal(isTestEnvironment({ NODE_ENV: "production" }), false);
});

test("missing production settings are reported by name only", () => {
  assert.deepEqual(
    missingWorkerSettings({ DATABASE_URL: "postgres://secret.invalid/db" }),
    [
      "TELEGRAM_BOT_TOKEN",
      "ADMIN_TELEGRAM_ID",
      "PRO_SIGNALS_CHANNEL_ID",
      "MARKET_ANALYSIS_CHANNEL_ID",
    ],
  );
  assert.deepEqual(missingWorkerSettings({}), [
    "TELEGRAM_BOT_TOKEN",
    "ADMIN_TELEGRAM_ID",
    "PRO_SIGNALS_CHANNEL_ID",
    "MARKET_ANALYSIS_CHANNEL_ID",
    "DATABASE_URL",
  ]);
});

test("workspace root detection finds the bot entry point above the API directory", () => {
  const existing = new Set([
    "/workspace/main.py",
    "/workspace/pyproject.toml",
  ]);
  assert.equal(
    resolveWorkspaceRoot("/workspace/artifacts/api-server", (candidate) => existing.has(candidate)),
    "/workspace",
  );
});

test("disabled worker does not spawn a process", () => {
  let spawnCalls = 0;
  const result = startTelegramWorker({
    env: { NODE_ENV: "production", SMH_ENABLE_TELEGRAM_WORKER: "false" },
    workspaceRoot: "/workspace",
    spawnProcess: () => {
      spawnCalls += 1;
      throw new Error("must not spawn");
    },
    log: () => {},
  });
  assert.equal(result.state, "disabled");
  assert.equal(spawnCalls, 0);
});

test("enabled worker uses the project virtualenv and never logs environment values", () => {
  const events = [];
  const fakeChild = new EventEmitter();
  fakeChild.exitCode = null;
  fakeChild.killed = false;
  let spawnArgs;
  const result = startTelegramWorker({
    env: productionEnv,
    workspaceRoot: "/workspace",
    pathExists: (filename) => filename === "/workspace/.venv/bin/python",
    spawnProcess: (...args) => {
      spawnArgs = args;
      return fakeChild;
    },
    log: (...args) => events.push(args),
  });

  assert.equal(result.state, "starting");
  assert.equal(spawnArgs[0], "/workspace/.venv/bin/python");
  assert.deepEqual(spawnArgs[1], ["main.py"]);
  assert.equal(spawnArgs[2].cwd, "/workspace");
  assert.equal(spawnArgs[2].env.TELEGRAM_BOT_TOKEN, productionEnv.TELEGRAM_BOT_TOKEN);
  assert.equal(JSON.stringify(events).includes(productionEnv.TELEGRAM_BOT_TOKEN), false);
  fakeChild.emit("spawn");
  assert.equal(result.state, "running");
});

test("worker fails closed for test settings or missing runtime dependencies", () => {
  const logs = [];
  const testResult = startTelegramWorker({
    env: { ...productionEnv, SMH_TEST_MODE: "1" },
    workspaceRoot: "/workspace",
    pathExists: () => true,
    spawnProcess: () => {
      throw new Error("must not spawn");
    },
    log: (...args) => logs.push(args),
  });
  assert.equal(testResult.state, "blocked");
  assert.deepEqual(logs[0], ["blocked", "test_environment_not_allowed"]);

  const pythonMissing = startTelegramWorker({
    env: productionEnv,
    workspaceRoot: "/workspace",
    pathExists: () => false,
    spawnProcess: () => {
      throw new Error("must not spawn");
    },
    log: (...args) => logs.push(args),
  });
  assert.equal(pythonMissing.state, "blocked");
  assert.deepEqual(logs.at(-1), ["blocked", "python_environment_missing"]);
});

test("worker stop requests a graceful SIGTERM", () => {
  let signal;
  stopTelegramWorker({
    exitCode: null,
    killed: false,
    kill: (value) => {
      signal = value;
      return true;
    },
  });
  assert.equal(signal, "SIGTERM");
});
