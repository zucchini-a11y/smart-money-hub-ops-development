import { randomUUID } from "node:crypto";
import { stdin, stdout } from "node:process";
import { StringDecoder } from "node:string_decoder";
import { pool } from "@workspace/db";
import { hashPassword } from "../lib/portal-crypto";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";

function readLine(prompt: string): Promise<string> {
  if (!stdin.isTTY) {
    throw new Error("Run this command in an interactive Development terminal.");
  }
  stdout.write(prompt);
  return new Promise((resolve, reject) => {
    let value = "";
    const onData = (chunk: Buffer): void => {
      const text = chunk.toString("utf8");
      for (const character of text) {
        if (character === "\u0003" || character === "\u0004") {
          stdin.removeListener("data", onData);
          stdin.pause();
          stdout.write("\n");
          reject(new Error("Owner setup cancelled."));
          return;
        }
        if (character === "\r" || character === "\n") {
          stdin.removeListener("data", onData);
          stdin.pause();
          stdout.write("\n");
          resolve(value.trim());
          return;
        }
        if (character === "\u007f" || character === "\b") {
          value = Array.from(value).slice(0, -1).join("");
        } else if (!/[\u0000-\u001f\u007f]/u.test(character)) {
          value += character;
        }
      }
    };
    stdin.resume();
    stdin.on("data", onData);
  });
}

function readHidden(prompt: string): Promise<string> {
  if (!stdin.isTTY || typeof stdin.setRawMode !== "function") {
    throw new Error("Run this command in an interactive Development terminal.");
  }
  stdout.write(prompt);
  stdin.setRawMode(true);
  stdin.resume();
  return new Promise((resolve, reject) => {
    let value = "";
    const decoder = new StringDecoder("utf8");
    const finish = (result?: string, error?: Error): void => {
      stdin.removeListener("data", onData);
      stdin.setRawMode(false);
      stdin.pause();
      stdout.write("\n");
      if (error) reject(error);
      else resolve(result ?? "");
    };
    const onData = (chunk: Buffer): void => {
      for (const character of decoder.write(chunk)) {
        if (character === "\u0003" || character === "\u0004") {
          finish(undefined, new Error("Owner setup cancelled."));
          return;
        }
        if (character === "\r" || character === "\n") {
          finish(value);
          return;
        }
        if (character === "\u007f" || character === "\b") {
          value = Array.from(value).slice(0, -1).join("");
        } else if (!/[\u0000-\u001f\u007f]/u.test(character)) {
          value += character;
        }
      }
    };
    stdin.on("data", onData);
  });
}

async function bootstrapDevelopmentOwner(): Promise<void> {
  const schema = resolvePortalSupportSchema(
    process.env.NODE_ENV,
    process.env.PORTAL_SUPPORT_SCHEMA,
  );
  if (schema !== "smh_test" || process.env.NODE_ENV === "production") {
    throw new Error("Refusing to create an Owner outside the Development smh_test schema.");
  }

  const email = (await readLine("Development Owner email: ")).toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) {
    throw new Error("Enter a valid email address. No account was created.");
  }
  const displayName = (await readLine("Display name [Development Owner]: ")) || "Development Owner";
  if (displayName.length > 80) {
    throw new Error("Display name must be 80 characters or fewer. No account was created.");
  }
  const password = await readHidden("New Development Owner password (12–256 characters, hidden): ");
  const confirmation = await readHidden("Confirm password (hidden): ");
  if (password.length < 12 || password.length > 256) {
    throw new Error("Password must be between 12 and 256 characters.");
  }
  if (password !== confirmation) {
    throw new Error("Passwords do not match. No account was created.");
  }

  const client = await pool.connect();
  let transactionOpen = false;
  try {
    await client.query("BEGIN");
    transactionOpen = true;
    await client.query(
      "SELECT pg_advisory_xact_lock(hashtextextended('smh_test.portal_owner.bootstrap', 0))",
    );

    const existingOwners = await client.query(
      `SELECT id FROM smh_test.portal_users
        WHERE role IN ('owner','admin')
        ORDER BY created,id
        FOR UPDATE`,
    );
    if (existingOwners.rows.length > 0) {
      throw new Error("A Development Owner account already exists. No account was created.");
    }

    const now = new Date().toISOString();
    const ownerId = randomUUID();
    await client.query(
      `INSERT INTO smh_test.portal_users
         (id,email,display_name,password_hash,role,active,must_change_password,created,updated,last_login)
       VALUES($1,$2,$3,$4,'owner',TRUE,TRUE,$5,$5,NULL)`,
      [ownerId, email, displayName, hashPassword(password), now],
    );
    await client.query(
      `INSERT INTO smh_test.portal_audit(id,actor_id,action,entity_id,created,detail)
       VALUES($1,$2,'development_owner_bootstrapped',$2,$3,'Initial Development Owner created in smh_test')`,
      [randomUUID(), ownerId, now],
    );
    await client.query("COMMIT");
    transactionOpen = false;
    stdout.write("Initial Development Owner created in smh_test. Sign in at /login and set a new password.\n");
  } catch (error) {
    if (transactionOpen) await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

try {
  await bootstrapDevelopmentOwner();
} catch (error) {
  const message = error instanceof Error ? error.message : "Unexpected error.";
  stdout.write(`Development Owner setup not completed: ${message}\n`);
  process.exitCode = 1;
} finally {
  await pool.end();
  if (stdin.isTTY) stdin.pause();
}
