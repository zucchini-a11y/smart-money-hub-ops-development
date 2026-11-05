import test from "node:test";
import assert from "node:assert/strict";
import { isAllowedDuringPasswordSetup } from "../src/lib/portal-auth-policy.ts";

test("temporary-password sessions can load the session and change or end the session", () => {
  assert.equal(isAllowedDuringPasswordSetup("GET", "/api/portal/auth/session"), true);
  assert.equal(isAllowedDuringPasswordSetup("POST", "/api/portal/auth/password"), true);
  assert.equal(isAllowedDuringPasswordSetup("POST", "/api/portal/auth/logout"), true);
});

test("temporary-password sessions cannot access support or staff data", () => {
  assert.equal(isAllowedDuringPasswordSetup("GET", "/api/portal/cases"), false);
  assert.equal(isAllowedDuringPasswordSetup("GET", "/api/portal/staff"), false);
  assert.equal(isAllowedDuringPasswordSetup("POST", "/api/portal/auth/session"), false);
});
