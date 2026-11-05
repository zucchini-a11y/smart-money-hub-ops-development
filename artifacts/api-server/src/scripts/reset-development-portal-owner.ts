import { randomUUID } from "node:crypto";
import { stdin, stdout } from "node:process";
import { StringDecoder } from "node:string_decoder";
import { pool } from "@workspace/db";
import { hashPassword } from "../lib/portal-crypto";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";

function readHidden(prompt: string): Promise<string> {
  if (!stdin.isTTY || typeof stdin.setRawMode !== "function") {
    throw new Error("Run this command in an interactive Replit Shell.");
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
          finish(undefined, new Error("Password reset cancelled."));
          return;
        }
        if (character === "\r" || character === "\n") {
          finish(value);
          return;
        }
        if (character === "\u007f" || character === "\b") {
          value = Array.from(value).slice(0, -1).join("");
          continue;
        }
        if (!/[\u0000-\u001f\u007f]/u.test(character)) value += character;
      }
    };

    stdin.on("data", onData);
  });
}

async function resetDevelopmentOwner(): Promise<void> {
  const schema = resolvePortalSupportSchema(
    process.env.NODE_ENV,
    process.env.PORTAL_SUPPORT_SCHEMA,
  );
  if (schema !== "smh_test" || process.env.NODE_ENV === "production") {
    throw new Error("This reset is restricted to the Development portal.");
  }

  const password = await readHidden("New Development password (12–256 characters, hidden): ");
  const confirmation = await readHidden("Confirm new password (hidden): ");
  if (password.length < 12 || password.length > 256) {
    throw new Error("Password must be between 12 and 256 characters.");
  }
  if (password !== confirmation) {
    throw new Error("Passwords do not match. No account was changed.");
  }

  const client = await pool.connect();
  let transactionOpen = false;
  try {
    await client.query("BEGIN");
    transactionOpen = true;
    const owners = await client.query(
      `SELECT id
         FROM smh_test.portal_users
        WHERE active=TRUE AND role IN ('owner','admin')
        ORDER BY created,id
        FOR UPDATE`,
    );
    if (owners.rows.length !== 1) {
      throw new Error("Expected exactly one active Development owner; no account was changed.");
    }

    const ownerId = String(owners.rows[0].id);
    const now = new Date().toISOString();
    await client.query(
      `UPDATE smh_test.portal_users
          SET password_hash=$1,must_change_password=FALSE,updated=$2
        WHERE id=$3`,
      [hashPassword(password), now, ownerId],
    );
    await client.query(
      "DELETE FROM smh_test.portal_sessions WHERE staff_id=$1",
      [ownerId],
    );
    await client.query(
      `INSERT INTO smh_test.portal_audit(id,actor_id,action,entity_id,created,detail)
       VALUES($1,$2,'development_password_reset',$2,$3,'Private Development Shell reset')`,
      [randomUUID(), ownerId, now],
    );
    await client.query("COMMIT");
    transactionOpen = false;
    stdout.write("Development owner password reset. Previous Development sessions were signed out.\n");
  } catch (error) {
    if (transactionOpen) {
      await client.query("ROLLBACK").catch(() => undefined);
    }
    throw error;
  } finally {
    client.release();
  }
}

try {
  await resetDevelopmentOwner();
} catch (error) {
  const message = error instanceof Error ? error.message : "Unexpected error.";
  console.error(`Development password reset not completed: ${message}`);
  process.exitCode = 1;
} finally {
  await pool.end();
  if (stdin.isTTY) stdin.pause();
}
