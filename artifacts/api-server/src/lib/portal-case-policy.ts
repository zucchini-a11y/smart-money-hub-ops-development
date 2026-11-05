export type PortalRole = "owner" | "manager" | "agent";

export function canManageStaff(role: PortalRole): boolean {
  return role === "owner";
}

export function canManageCases(role: PortalRole): boolean {
  return role === "owner" || role === "manager";
}

export function canAccessCase(
  role: PortalRole,
  staffId: string,
  assignedStaffId: string | null,
): boolean {
  return canManageCases(role) || assignedStaffId === staffId;
}
