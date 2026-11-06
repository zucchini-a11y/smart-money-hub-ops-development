import type { PortalSupportSchema } from "./portal-support-schema";

const ACTIVE_PRO_ACCESS_STATUSES = new Set(["joined", "member", "administrator", "creator"]);
const VERIFIED_REGISTRATION_STATUSES = new Set(["approved", "verified"]);
const POSTGRES_BIGINT_MIN = -(2n ** 63n);
const POSTGRES_BIGINT_MAX = 2n ** 63n - 1n;

export function developmentProSignalsChannelId(
  nodeEnvironment: string | undefined,
  schema: PortalSupportSchema,
  configuredChannelId: string | undefined,
): string | null {
  if (nodeEnvironment !== "development" || schema !== "smh_test") return null;
  const value = configuredChannelId?.trim();
  if (!value || !/^-?\d{1,19}$/.test(value)) return null;
  try {
    const parsed = BigInt(value);
    if (parsed === 0n || parsed < POSTGRES_BIGINT_MIN || parsed > POSTGRES_BIGINT_MAX) return null;
  } catch {
    return null;
  }
  return value;
}

export function hasActiveProSignalsEntitlement(input: {
  requestStatus?: string | null;
  registrationStatus?: string | null;
  fundingStatus?: string | null;
  telegramAccessStatus?: string | null;
}): boolean {
  return input.requestStatus === "approved"
    && VERIFIED_REGISTRATION_STATUSES.has(input.registrationStatus ?? "")
    && input.fundingStatus === "verified"
    && ACTIVE_PRO_ACCESS_STATUSES.has(input.telegramAccessStatus ?? "");
}
