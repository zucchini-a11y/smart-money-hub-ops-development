import { stdin, stdout } from "node:process";
import { StringDecoder } from "node:string_decoder";
import { pool } from "@workspace/db";
import { verifyPassword } from "../lib/portal-crypto";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";

function readLine(prompt: string): Promise<string> {
  return new Promise((resolve) => {
    stdout.write(prompt);
    let value = "";
    const onData = (chunk: Buffer): void => {
      for (const character of chunk.toString("utf8")) {
        if (character === "\r" || character === "\n") {
          stdin.removeListener("data", onData);
          stdin.pause();
          stdout.write("\n");
          resolve(value);
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
    throw new Error("Run this check in an interactive Replit Shell.");
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
          finish(undefined, new Error("Password check cancelled."));
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

async function checkDevelopmentOwnerPassword(): Promise<void> {
  const schema = resolvePortalSupportSchema(
    process.env.NODE_ENV,
    process.env.PORTAL_SUPPORT_SCHEMA,
  );
  if (schema !== "smh_test" || process.env.NODE_ENV === "production") {
    throw new Error("This check is restricted to the Development portal.");
  }

  const email = (await readLine("Development Owner email: ")).trim().toLowerCase();
  const password = await readHidden("Password to check (hidden): ");
  const result = await pool.query(
    `SELECT password_hash
       FROM smh_test.portal_users
      WHERE lower(email)=$1 AND role IN ('owner','admin') AND active=TRUE`,
    [email],
  );

  if (result.rows.length !== 1) {
    stdout.write("No unique active Development Owner account matched. No data was changed.\n");
    return;
  }

  const matches = verifyPassword(password, String(result.rows[0].password_hash));
  stdout.write(
    matches
      ? "Password matches the active Development Owner record. No data was changed.\n"
      : "Password does not match the active Development Owner record. No data was changed.\n",
  );
}

try {
  await checkDevelopmentOwnerPassword();
} catch (error) {
  const message = error instanceof Error ? error.message : "Unexpected error.";
  console.error(`Development password check not completed: ${message}`);
  process.exitCode = 1;
} finally {
  await pool.end();
}
