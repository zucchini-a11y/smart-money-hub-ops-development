type MemberNameSource = {
  firstName?: string | null;
  lastName?: string | null;
  username?: string | null;
  unsafeMetadata?: Record<string, unknown> | null;
  email: string;
};

function cleanName(value: unknown): string {
  if (typeof value !== "string") return "";
  return value.replace(/\p{Cc}/gu, "").trim().replace(/\s+/g, " ").slice(0, 120);
}

function titleCasePart(part: string): string {
  const characters = Array.from(part);
  if (!characters.length) return "";
  return characters[0].toLocaleUpperCase() + characters.slice(1).join("");
}

function nameFromEmail(email: string): string {
  const at = email.lastIndexOf("@");
  if (at <= 0) return "";

  const localPart = email.slice(0, at).split("+", 1)[0];
  const parts = localPart
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .map(titleCasePart);
  return cleanName(parts.join(" "));
}

export function memberDisplayName(user: MemberNameSource): string {
  const profileName = cleanName(user.unsafeMetadata?.fullName);
  const fullName = cleanName([user.firstName, user.lastName].filter(Boolean).join(" "));
  if (fullName) return fullName;
  if (profileName) return profileName;

  const username = cleanName(user.username);
  if (username && !username.includes("@")) return username;

  return nameFromEmail(user.email) || "Member";
}
