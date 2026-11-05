export type PortalSupportSchema = "smh" | "smh_test";

export function resolvePortalSupportSchema(
  nodeEnvironment: string | undefined,
  configuredSchema: string | undefined,
): PortalSupportSchema {
  if (nodeEnvironment === "production") {
    if (configuredSchema === "smh_test") {
      throw new Error("Production cannot use the Development portal schema.");
    }
    return "smh";
  }
  if (!configuredSchema || configuredSchema === "smh_test") return "smh_test";
  if (configuredSchema === "smh") {
    throw new Error("Development cannot use the Production portal schema.");
  }
  throw new Error("PORTAL_SUPPORT_SCHEMA must be smh or smh_test.");
}
