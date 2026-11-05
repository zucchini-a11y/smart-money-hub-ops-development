export function isDevelopmentCommandCenterAvailable(
  nodeEnvironment: string | undefined,
  supportSchema: string,
): boolean {
  return nodeEnvironment === "development" && supportSchema === "smh_test";
}

export function canViewOwnerCommandCenter(role: string): boolean {
  return role === "owner";
}
