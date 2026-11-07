import assert from "node:assert/strict";
import test from "node:test";
import { checkTelegramIdentity } from "../src/lib/telegram-identity-check.ts";

const jsonResponse = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

test("missing bot credentials stay unconfigured without an outbound request", async () => {
  let called = false;
  const result = await checkTelegramIdentity(undefined, null, async () => {
    called = true;
    throw new Error("must not call Telegram");
  });
  assert.deepEqual(result, { identityStatus: "not_configured", username: null });
  assert.equal(called, false);
});

test("read-only getMe validates the expected bot identity", async () => {
  let requestUrl = "";
  const result = await checkTelegramIdentity("hidden-token", "@CoachBot", async (url) => {
    requestUrl = String(url);
    return jsonResponse({ ok: true, result: { username: "CoachBot" } });
  });
  assert.equal(result.identityStatus, "verified");
  assert.equal(result.username, "CoachBot");
  assert.match(requestUrl, /\/getMe$/);
  assert.doesNotMatch(JSON.stringify(result), /hidden-token/);
});

test("wrong bot identity is reported without being called connected", async () => {
  const result = await checkTelegramIdentity("hidden-token", "ExpectedBot", async () =>
    jsonResponse({ ok: true, result: { username: "DifferentBot" } }));
  assert.deepEqual(result, {
    identityStatus: "identity_mismatch",
    username: "DifferentBot",
  });
});

test("Telegram token rejection and network errors are safely classified", async () => {
  const invalid = await checkTelegramIdentity("hidden-token", null, async () =>
    jsonResponse({ ok: false, error_code: 401 }, 401));
  const unavailable = await checkTelegramIdentity("hidden-token", null, async () => {
    throw new Error("secret-containing URL must not escape");
  });
  assert.equal(invalid.identityStatus, "invalid_credentials");
  assert.equal(unavailable.identityStatus, "unavailable");
  assert.equal(invalid.username, null);
  assert.equal(unavailable.username, null);
});
