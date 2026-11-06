import assert from "node:assert/strict";
import test from "node:test";
import {
  developmentProSignalsChannelId,
  hasActiveProSignalsEntitlement,
} from "../src/lib/pro-signals-entitlement.ts";

const approved = {
  requestStatus: "approved",
  registrationStatus: "verified",
  fundingStatus: "verified",
  telegramAccessStatus: "member",
};

test("PRO entitlement requires a verified approved request and active Telegram membership", () => {
  assert.equal(hasActiveProSignalsEntitlement(approved), true);
  for (const override of [
    { requestStatus: "pending" },
    { requestStatus: "revoked" },
    { registrationStatus: "pending_review" },
    { fundingStatus: "pending_review" },
    { fundingStatus: "unverified" },
    { telegramAccessStatus: "invite_issued" },
    { telegramAccessStatus: "access_revoked" },
    { telegramAccessStatus: "left" },
  ]) {
    assert.equal(hasActiveProSignalsEntitlement({ ...approved, ...override }), false);
  }
});

test("only a valid Development channel ID can enable Development PRO checks", () => {
  assert.equal(developmentProSignalsChannelId("development", "smh_test", "-1001234567890"), "-1001234567890");
  assert.equal(developmentProSignalsChannelId("production", "smh", "-1001234567890"), null);
  assert.equal(developmentProSignalsChannelId("development", "smh", "-1001234567890"), null);
  assert.equal(developmentProSignalsChannelId("development", "smh_test", ""), null);
  assert.equal(developmentProSignalsChannelId("development", "smh_test", "not-a-channel"), null);
  assert.equal(developmentProSignalsChannelId("development", "smh_test", "9223372036854775808"), null);
});
