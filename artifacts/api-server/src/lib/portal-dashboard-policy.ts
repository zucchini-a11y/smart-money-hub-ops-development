import type { PortalRole } from "./portal-case-policy";

export const MEMBER_DASHBOARD_PATH = "/member/dashboard";

export function portalDashboardPath(role: PortalRole): string {
  if (role === "owner") return "/command-center";
  if (role === "manager") return "/staff";
  return "/staff/support";
}

export function memberDashboardEntitlements(proSignalsAccess = false) {
  return {
    learningDashboard: true,
    proSignalsAccess,
  };
}
