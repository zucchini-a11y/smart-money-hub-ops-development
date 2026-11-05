import test from "node:test";
import assert from "node:assert/strict";
import {
  canViewOwnerCommandCenter,
  isDevelopmentCommandCenterAvailable,
} from "../src/lib/owner-command-center-policy.ts";

test("owner command center is enabled only for the Development isolated-test schema", () => {
  assert.equal(isDevelopmentCommandCenterAvailable("development", "smh_test"), true);
  assert.equal(isDevelopmentCommandCenterAvailable("production", "smh_test"), false);
  assert.equal(isDevelopmentCommandCenterAvailable("development", "smh"), false);
  assert.equal(isDevelopmentCommandCenterAvailable(undefined, "smh_test"), false);
});

test("only the owner can access command-center data", () => {
  assert.equal(canViewOwnerCommandCenter("owner"), true);
  assert.equal(canViewOwnerCommandCenter("manager"), false);
  assert.equal(canViewOwnerCommandCenter("agent"), false);
});
