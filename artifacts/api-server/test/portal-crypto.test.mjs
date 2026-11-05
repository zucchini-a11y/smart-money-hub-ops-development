import test from "node:test";
import assert from "node:assert/strict";
import {
  hashPassword,
  hashSessionToken,
  makeSessionToken,
  makeTemporaryPassword,
  verifyPassword,
} from "../src/lib/portal-crypto.ts";

test("password hashes verify the correct password and reject another", () => {
  const hash = hashPassword("synthetic-test-password-only");
  assert.match(hash, /^scrypt\$16384\$8\$1\$[a-f0-9]{32}\$[a-f0-9]{128}$/);
  assert.equal(verifyPassword("synthetic-test-password-only", hash), true);
  assert.equal(verifyPassword("different-password", hash), false);
  assert.equal(verifyPassword("anything", "not-a-valid-hash"), false);
});

test("session and temporary passwords are unpredictable-format values and session storage is hashed", () => {
  const temporary = makeTemporaryPassword();
  const session = makeSessionToken();
  assert.match(temporary, /^[A-Za-z0-9_-]{20,}$/);
  assert.match(session, /^[A-Za-z0-9_-]{40,}$/);
  const digest = hashSessionToken(session);
  assert.match(digest, /^[a-f0-9]{64}$/);
  assert.notEqual(digest, session);
});
