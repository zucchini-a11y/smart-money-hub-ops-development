import { readFile } from "node:fs/promises";
import { pool } from "@workspace/db";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";

async function main(): Promise<void> {
  if (process.env.NODE_ENV === "production") {
    throw new Error("Refusing to run a Development-only migration in Production.");
  }
  const schema = resolvePortalSupportSchema(
    process.env.NODE_ENV,
    process.env.PORTAL_SUPPORT_SCHEMA,
  );
  if (schema !== "smh_test") {
    throw new Error("Refusing to run unless the selected schema is smh_test.");
  }

  const migration = new URL(
    "../../migrations/portal-development/023_member_notifications.sql",
    import.meta.url,
  );
  const sql = await readFile(migration, "utf8");
  await pool.query(sql);
  console.log("Development member notifications migration applied to smh_test.");
}

main()
  .catch((error: unknown) => {
    console.error(
      error instanceof Error
        ? error.message
        : "Development member notifications migration failed.",
    );
    process.exitCode = 1;
  })
  .finally(async () => {
    await pool.end();
  });
