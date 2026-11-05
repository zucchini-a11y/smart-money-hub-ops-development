import test from "node:test";
import assert from "node:assert/strict";
import { canAccessStaffTask, mayChangeTaskStatus } from "../src/lib/staff-task-policy.ts";

test("task visibility is limited by role, assignment, and team membership", () => {
  const teamTask = { teamId: "team-a", assignedStaffId: null };
  const individualTask = { teamId: "team-a", assignedStaffId: "worker-a" };
  assert.equal(canAccessStaffTask("owner", "owner-1", individualTask, null), true);
  assert.equal(canAccessStaffTask("manager", "manager-a", teamTask, "manager"), true);
  assert.equal(canAccessStaffTask("manager", "manager-b", teamTask, null), false);
  assert.equal(canAccessStaffTask("agent", "worker-a", individualTask, null), true);
  assert.equal(canAccessStaffTask("agent", "worker-b", individualTask, "worker"), false);
  assert.equal(canAccessStaffTask("agent", "worker-b", teamTask, "worker"), true);
});

test("workers follow the defined lifecycle and cannot approve their own work", () => {
  assert.equal(mayChangeTaskStatus("agent", "assigned", "accepted", false, true), true);
  assert.equal(mayChangeTaskStatus("agent", "accepted", "in_progress", false, true), true);
  assert.equal(mayChangeTaskStatus("agent", "in_progress", "submitted_for_review", false, true), true);
  assert.equal(mayChangeTaskStatus("agent", "submitted_for_review", "approved", false, true), false);
  assert.equal(mayChangeTaskStatus("manager", "submitted_for_review", "approved", true, false), true);
  assert.equal(mayChangeTaskStatus("manager", "submitted_for_review", "approved", false, false), false);
  assert.equal(mayChangeTaskStatus("agent", "assigned", "cancelled", false, true), false);
});
