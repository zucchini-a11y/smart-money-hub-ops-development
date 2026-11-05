import test from "node:test";
import assert from "node:assert/strict";
import { resolvePortalSupportSchema } from "../src/lib/portal-support-schema.ts";

test("development can route support cases to the isolated test schema", () => {
  assert.equal(resolvePortalSupportSchema("development", "smh_test"), "smh_test");
});

test("production refuses the development schema", () => {
  assert.throws(
    () => resolvePortalSupportSchema("production", "smh_test"),
    /Production cannot use the Development portal schema/,
  );
});

test("an unset runtime environment defaults to the isolated test schema", () => {
  assert.equal(resolvePortalSupportSchema(undefined, "smh_test"), "smh_test");
});

test("unknown schema names fail closed", () => {
  assert.throws(() => resolvePortalSupportSchema("development", "unexpected"), /PORTAL_SUPPORT_SCHEMA/);
});
