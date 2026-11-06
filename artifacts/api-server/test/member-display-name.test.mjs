import test from "node:test";
import assert from "node:assert/strict";
import { memberDisplayName } from "../src/lib/member-display-name.ts";

test("member greeting uses the account's first and last name", () => {
  assert.equal(memberDisplayName({
    firstName: "  Ada ",
    lastName: "Lovelace ",
    email: "ada.lovelace@gmail.com",
  }), "Ada Lovelace");
});

test("member greeting falls back to the registration full name", () => {
  assert.equal(memberDisplayName({
    email: "ada.lovelace@gmail.com",
    unsafeMetadata: { fullName: "Ada Lovelace" },
  }), "Ada Lovelace");
});

test("member greeting never uses an email username or domain as the name", () => {
  assert.equal(memberDisplayName({
    email: "ada.lovelace+academy@gmail.com",
    username: "ada.lovelace@gmail.com",
  }), "Ada Lovelace");
});

test("member greeting uses a non-email username before deriving one from email", () => {
  assert.equal(memberDisplayName({
    email: "ada.lovelace@gmail.com",
    username: "Ada L",
  }), "Ada L");
});

test("member greeting uses a neutral label when no usable name exists", () => {
  assert.equal(memberDisplayName({ email: "not-an-email" }), "Member");
});
