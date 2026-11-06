import assert from "node:assert/strict";
import test from "node:test";
import { MEMBER_DASHBOARD_PATH, memberDashboardEntitlements, portalDashboardPath } from "./portal-dashboard-policy";

test("staff roles receive only their server-assigned landing route", () => {
  assert.equal(portalDashboardPath("owner"), "/command-center");
  assert.equal(portalDashboardPath("manager"), "/staff");
  assert.equal(portalDashboardPath("agent"), "/staff/support");
});

test("member registration grants learning dashboard only, never PRO Signals by default", () => {
  assert.equal(MEMBER_DASHBOARD_PATH, "/member/dashboard");
  assert.deepEqual(memberDashboardEntitlements(), {
    learningDashboard: true,
    proSignalsAccess: false,
  });
  assert.deepEqual(memberDashboardEntitlements(true), {
    learningDashboard: true,
    proSignalsAccess: true,
  });
});
