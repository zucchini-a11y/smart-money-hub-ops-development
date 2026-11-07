export type TelegramIdentityStatus =
  | "verified"
  | "not_configured"
  | "invalid_credentials"
  | "identity_mismatch"
  | "unavailable";

export interface TelegramIdentityCheck {
  identityStatus: TelegramIdentityStatus;
  username: string | null;
}

type TelegramGetMeResponse = {
  ok?: boolean;
  error_code?: number;
  result?: {
    username?: string;
  };
};

export async function checkTelegramIdentity(
  token: string | undefined,
  expectedUsername: string | null,
  fetcher: typeof fetch = fetch,
): Promise<TelegramIdentityCheck> {
  const configuredToken = token?.trim();
  if (!configuredToken) {
    return { identityStatus: "not_configured", username: null };
  }

  try {
    const response = await fetcher(
      `https://api.telegram.org/bot${configuredToken}/getMe`,
      { method: "GET", signal: AbortSignal.timeout(5_000) },
    );
    let body: TelegramGetMeResponse;
    try {
      body = await response.json() as TelegramGetMeResponse;
    } catch {
      return { identityStatus: "unavailable", username: null };
    }

    if (!response.ok || body.ok !== true) {
      const status = response.status || body.error_code;
      return {
        identityStatus: status === 401 || status === 404
          ? "invalid_credentials"
          : "unavailable",
        username: null,
      };
    }

    const username = typeof body.result?.username === "string"
      ? body.result.username.replace(/^@/, "")
      : null;
    if (!username) {
      return { identityStatus: "unavailable", username: null };
    }
    if (
      expectedUsername &&
      username.toLowerCase() !== expectedUsername.replace(/^@/, "").toLowerCase()
    ) {
      return { identityStatus: "identity_mismatch", username };
    }
    return { identityStatus: "verified", username };
  } catch {
    return { identityStatus: "unavailable", username: null };
  }
}
