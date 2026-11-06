import test from "node:test";
import assert from "node:assert/strict";
import { isWebsiteSupportEnabled } from "../src/lib/website-support-policy.ts";

test("Development support is enabled only on the isolated test schema", () => {
  assert.equal(isWebsiteSupportEnabled("development", "smh_test", undefined), true);
  assert.equal(isWebsiteSupportEnabled("development", "smh", "true"), false);
});

test("Production support is disabled unless explicitly enabled on the production schema", () => {
  assert.equal(isWebsiteSupportEnabled("production", "smh", undefined), false);
  assert.equal(isWebsiteSupportEnabled("production", "smh", "false"), false);
  assert.equal(isWebsiteSupportEnabled("production", "smh_test", "true"), false);
  assert.equal(isWebsiteSupportEnabled("production", "smh", "true"), true);
});

test("unset and non-production environments remain isolated to the test schema", () => {
  assert.equal(isWebsiteSupportEnabled(undefined, "smh_test", undefined), true);
  assert.equal(isWebsiteSupportEnabled("test", "smh", "true"), false);
});
