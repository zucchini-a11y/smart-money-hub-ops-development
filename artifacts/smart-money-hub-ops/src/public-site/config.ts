/**
 * Public-only destinations. Values prefixed with VITE_ are public build-time
 * settings; never put credentials or private API URLs here.
 */
const configured = (value: string | undefined) => value?.trim() ?? "";

export const publicSiteLinks = {
  primaryCommunity: "https://t.me/SmartMoneyHubSignalsBot",
  proSignalsAssistant: "https://t.me/SMHProSignalsassistantbot",
  educationChannel: configured(import.meta.env.VITE_PUBLIC_EDUCATION_URL),
  marketAnalysisChannel: configured(import.meta.env.VITE_PUBLIC_MARKET_ANALYSIS_URL),
  generalCommunity: configured(import.meta.env.VITE_PUBLIC_GENERAL_COMMUNITY_URL),
  contactUrl: configured(import.meta.env.VITE_PUBLIC_CONTACT_URL),
  contactEmail: configured(import.meta.env.VITE_PUBLIC_CONTACT_EMAIL),
} as const;

export function isConfiguredPublicUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}
