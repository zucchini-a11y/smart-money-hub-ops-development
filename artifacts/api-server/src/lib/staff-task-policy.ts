import type { PortalRole } from "./portal-case-policy";

export type StaffTaskStatus =
  | "assigned"
  | "accepted"
  | "in_progress"
  | "submitted_for_review"
  | "revision_requested"
  | "approved"
  | "cancelled";

export function canAccessStaffTask(
  role: PortalRole,
  staffId: string,
  task: { teamId: string | null; assignedStaffId: string | null },
  teamRole: "manager" | "worker" | null,
): boolean {
  if (role === "owner") return true;
  if (role === "manager") return task.teamId !== null && teamRole === "manager";
  if (task.assignedStaffId === staffId) return true;
  return task.teamId !== null && task.assignedStaffId === null && teamRole === "worker";
}

export function mayChangeTaskStatus(
  role: PortalRole,
  current: StaffTaskStatus,
  next: StaffTaskStatus,
  isAuthorizedTeamManager: boolean,
  isAssignedWorker: boolean,
): boolean {
  if (next === "cancelled") return role === "owner";
  if (next === "approved" || next === "revision_requested") {
    return (role === "owner" || (role === "manager" && isAuthorizedTeamManager))
      && current === "submitted_for_review";
  }
  if (!isAssignedWorker) return false;
  return (
    (current === "assigned" && next === "accepted")
    || (current === "accepted" && next === "in_progress")
    || (current === "in_progress" && next === "submitted_for_review")
    || (current === "revision_requested" && next === "in_progress")
  );
}
