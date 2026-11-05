import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { Router, type IRouter, type Request, type Response } from "express";
import { clerkClient, getAuth } from "@clerk/express";
import { pool } from "@workspace/db";
import {
  GetMemberSessionResponse,
  LinkMemberTelegramBody,
  LinkMemberTelegramResponse,
} from "@workspace/api-zod";
import { MEMBER_DASHBOARD_PATH, memberDashboardEntitlements } from "../lib/portal-dashboard-policy";
import { requireSameOrigin } from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";

const router: IRouter = Router();
const schema = resolvePortalSupportSchema(process.env.NODE_ENV, process.env.PORTAL_SUPPORT_SCHEMA);
const telegramWidgetMaxAgeSeconds = 120;

function memberAuthEnabled(): boolean {
  return process.env.NODE_ENV !== "production" || process.env.SMH_MEMBER_AUTH_ENABLED === "true";
}

type MemberIdentity = {
  clerkUserId: string;
  email: string;
  displayName: string;
};

async function requireMemberIdentity(req: Request, res: Response): Promise<MemberIdentity | null> {
  if (!memberAuthEnabled()) {
    res.status(404).json({ error: "Member sign-in is not enabled in this environment." });
    return null;
  }
  const clerkUserId = getAuth(req).userId;
  if (!clerkUserId) {
    res.status(401).json({ error: "Sign in to continue." });
    return null;
  }

  const user = await clerkClient.users.getUser(clerkUserId);
  if (user.banned) {
    res.status(403).json({ error: "This account is not authorized to access the member dashboard." });
    return null;
  }

  const primaryEmail = user.emailAddresses.find((item) => item.id === user.primaryEmailAddressId);
  const verifiedEmail = primaryEmail?.verification?.status === "verified"
    ? primaryEmail
    : user.emailAddresses.find((item) => item.verification?.status === "verified");
  if (!verifiedEmail) {
    res.status(403).json({ error: "Verify your email address before opening the member dashboard." });
    return null;
  }

  const email = verifiedEmail.emailAddress.trim().toLowerCase();
  const staff = await pool.query(
    `SELECT id FROM ${schema}.portal_users WHERE lower(email)=$1 AND active=TRUE LIMIT 1`,
    [email],
  );
  if (staff.rows.length) {
    res.status(403).json({ error: "Use the shared sign-in page with your staff account." });
    return null;
  }

  const name = [user.firstName, user.lastName].filter(Boolean).join(" ").trim();
  return {
    clerkUserId,
    email,
    displayName: name || user.username || email,
  };
}

function sessionPayload(identity: MemberIdentity, telegramUsername: string | null) {
  return GetMemberSessionResponse.parse({
    accountType: "member",
    email: identity.email,
    displayName: identity.displayName,
    dashboardPath: MEMBER_DASHBOARD_PATH,
    ...memberDashboardEntitlements(),
    telegramLinked: telegramUsername !== null,
    telegramUsername,
  });
}

router.get("/member/session", async (req, res): Promise<void> => {
  res.setHeader("Cache-Control", "no-store");
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  const link = await pool.query(
    `SELECT telegram_username FROM ${schema}.member_telegram_links WHERE clerk_user_id=$1 LIMIT 1`,
    [identity.clerkUserId],
  );
  res.json(sessionPayload(identity, link.rows[0]?.telegram_username == null
    ? null : String(link.rows[0].telegram_username)));
});

router.post("/member/telegram/link", requireSameOrigin, async (req, res): Promise<void> => {
  res.setHeader("Cache-Control", "no-store");
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  const parsed = LinkMemberTelegramBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Telegram did not return a valid identity proof." });
    return;
  }
  const botToken = process.env.TELEGRAM_BOT_TOKEN?.trim();
  if (!botToken) {
    res.status(503).json({ error: "Telegram identity linking is not configured." });
    return;
  }

  const { id, authDate, hash, username, firstName, lastName, photoUrl } = parsed.data;
  if (!/^\d{1,30}$/.test(id) || !Number.isSafeInteger(authDate)) {
    res.status(400).json({ error: "Telegram did not return a valid identity proof." });
    return;
  }
  const now = Math.floor(Date.now() / 1000);
  if (authDate > now + 30 || now - authDate > telegramWidgetMaxAgeSeconds) {
    res.status(401).json({ error: "That Telegram sign-in proof has expired. Try linking again." });
    return;
  }

  const fields: Array<[string, string | undefined]> = [
    ["auth_date", String(authDate)],
    ["first_name", firstName],
    ["id", id],
    ["last_name", lastName],
    ["photo_url", photoUrl],
    ["username", username],
  ];
  const dataCheckString = fields
    .filter(([, value]) => value !== undefined && value !== "")
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
  const secretKey = createHash("sha256").update(botToken).digest();
  const expectedHash = createHmac("sha256", secretKey).update(dataCheckString).digest();
  const suppliedHash = Buffer.from(hash, "hex");
  if (suppliedHash.length !== expectedHash.length || !timingSafeEqual(suppliedHash, expectedHash)) {
    res.status(401).json({ error: "Telegram identity could not be verified." });
    return;
  }

  const existing = await pool.query(
    `SELECT telegram_user_id,telegram_username,telegram_auth_hash
       FROM ${schema}.member_telegram_links WHERE clerk_user_id=$1 LIMIT 1`,
    [identity.clerkUserId],
  );
  if (existing.rows[0] && String(existing.rows[0].telegram_user_id) !== id) {
    res.status(409).json({ error: "A different Telegram account is already linked. Contact support to change it." });
    return;
  }

  const consumed = await pool.query(
    `SELECT clerk_user_id FROM ${schema}.member_telegram_links WHERE telegram_auth_hash=$1 LIMIT 1`,
    [hash],
  );
  if (consumed.rows[0] && String(consumed.rows[0].clerk_user_id) !== identity.clerkUserId) {
    res.status(409).json({ error: "That Telegram sign-in proof has already been used." });
    return;
  }

  if (existing.rows[0] && String(existing.rows[0].telegram_auth_hash) === hash) {
    res.json(LinkMemberTelegramResponse.parse({
      linked: true,
      telegramUsername: existing.rows[0].telegram_username == null ? null : String(existing.rows[0].telegram_username),
    }));
    return;
  }

  try {
    const result = await pool.query(
      `INSERT INTO ${schema}.member_telegram_links
         (clerk_user_id,telegram_user_id,telegram_username,telegram_auth_hash,linked_at)
       VALUES($1,$2,$3,$4,NOW())
       ON CONFLICT (clerk_user_id) DO UPDATE
         SET telegram_username=EXCLUDED.telegram_username,
             telegram_auth_hash=EXCLUDED.telegram_auth_hash,
             linked_at=EXCLUDED.linked_at
       RETURNING telegram_username`,
      [identity.clerkUserId, id, username ?? null, hash],
    );
    res.json(LinkMemberTelegramResponse.parse({
      linked: true,
      telegramUsername: result.rows[0]?.telegram_username == null ? null : String(result.rows[0].telegram_username),
    }));
  } catch (error) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "23505") {
      res.status(409).json({ error: "That Telegram account is already linked to another member." });
      return;
    }
    throw error;
  }
});

export default router;
