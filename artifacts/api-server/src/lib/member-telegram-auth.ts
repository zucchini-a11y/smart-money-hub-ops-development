export function memberTelegramBotToken(
  nodeEnvironment: string | undefined,
  env: Record<string, string | undefined> = process.env,
): string | null {
  const tokenName = nodeEnvironment === "development"
    ? "SMH_PRO_SIGNALS_BOT_TOKEN"
    : nodeEnvironment === "production"
      ? "TELEGRAM_BOT_TOKEN"
      : null;
  return tokenName ? env[tokenName]?.trim() || null : null;
}
