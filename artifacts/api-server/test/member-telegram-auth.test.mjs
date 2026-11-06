import assert from "node:assert/strict";
import test from "node:test";
import { memberTelegramBotToken } from "../src/lib/member-telegram-auth.ts";

test("Development Telegram identity checks use only the PRO Signals bot token", () => {
  assert.equal(memberTelegramBotToken("development", {
    SMH_PRO_SIGNALS_BOT_TOKEN: "  development-pro-token  ",
    TELEGRAM_BOT_TOKEN: "existing-main-bot-token",
  }), "development-pro-token");
});

test("Production Telegram identity checks retain the existing bot token", () => {
  assert.equal(memberTelegramBotToken("production", {
    SMH_PRO_SIGNALS_BOT_TOKEN: "development-pro-token",
    TELEGRAM_BOT_TOKEN: "production-main-bot-token",
  }), "production-main-bot-token");
});

test("missing or non-development configuration does not fall back to another bot", () => {
  assert.equal(memberTelegramBotToken("development", { TELEGRAM_BOT_TOKEN: "main-bot-token" }), null);
  assert.equal(memberTelegramBotToken("test", { SMH_PRO_SIGNALS_BOT_TOKEN: "pro-token" }), null);
});
