import test from "node:test";
import assert from "node:assert/strict";
import {
  canAccessCase,
  canManageCases,
  canManageStaff,
} from "../src/lib/portal-case-policy.ts";

test("owner and manager can review cases, but only owner can manage staff", () => {
  for (const role of ["owner", "manager"]) {
    assert.equal(canManageCases(role), true);
  }
  assert.equal(canManageStaff("owner"), true);
  assert.equal(canManageStaff("manager"), false);
  assert.equal(canManageStaff("agent"), false);
});

test("agents can access only cases assigned to their own account", () => {
  assert.equal(canAccessCase("agent", "agent-1", "agent-1"), true);
  assert.equal(canAccessCase("agent", "agent-1", "agent-2"), false);
  assert.equal(canAccessCase("agent", "agent-1", null), false);
  assert.equal(canAccessCase("manager", "manager-1", null), true);
});
