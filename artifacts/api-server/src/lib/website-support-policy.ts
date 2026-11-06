import type { PortalSupportSchema } from "./portal-support-schema";

/**
 * Keep public website support isolated in Development and explicitly opt-in
 * in Production. Production schema selection is independently fail-closed by
 * resolvePortalSupportSchema.
 */
export function isWebsiteSupportEnabled(
  nodeEnvironment: string | undefined,
  supportSchema: PortalSupportSchema,
  configuredFlag: string | undefined,
): boolean {
  if (nodeEnvironment === "production") {
    return supportSchema === "smh" && configuredFlag === "true";
  }
  return supportSchema === "smh_test";
}
