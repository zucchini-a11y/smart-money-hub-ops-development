import type { NextFunction, Request, Response } from "express";
import { pool } from "@workspace/db";
import {
  hashSessionToken,
} from "./portal-crypto";
import { isAllowedDuringPasswordSetup } from "./portal-auth-policy";
import { portalDashboardPath } from "./portal-dashboard-policy";
import type { PortalRole } from "./portal-case-policy";
import { resolvePortalSupportSchema } from "./portal-support-schema";

const supportSchema = resolvePortalSupportSchema(
  process.env.NODE_ENV,
  process.env.PORTAL_SUPPORT_SCHEMA,
);

export interface PortalIdentity {
  id: string;
  email: string;
  displayName: string;
  role: PortalRole;
  mustChangePassword: boolean;
}

declare global {
  namespace Express {
    interface Request {
      portalIdentity?: PortalIdentity;
      portalSessionHash?: string;
    }
  }
}

const COOKIE_NAME = "smh_portal_session";
const SESSION_HOURS = 8;
function readCookie(header: string | undefined): string | null {
  if (!header) return null;
  for (const segment of header.split(";")) {
    const [name, ...rest] = segment.trim().split("=");
    if (name === COOKIE_NAME) {
      try {
        return decodeURIComponent(rest.join("="));
      } catch {
        return null;
      }
    }
  }
  return null;
}

export function setPortalSessionCookie(req: Request, res: Response, token: string): void {
  const secure = process.env.NODE_ENV === "production" ||
    req.get("x-forwarded-proto")?.split(",")[0].trim() === "https";
  res.setHeader(
    "Set-Cookie",
    `${COOKIE_NAME}=${encodeURIComponent(token)}; Path=/api; HttpOnly; SameSite=Strict; Max-Age=${SESSION_HOURS * 60 * 60}${secure ? "; Secure" : ""}`,
  );
  res.appendHeader(
    "Set-Cookie",
    `${COOKIE_NAME}=; Path=/api/portal; HttpOnly; SameSite=Strict; Max-Age=0${secure ? "; Secure" : ""}`,
  );
  res.setHeader("Cache-Control", "no-store");
}

export function clearPortalSessionCookie(req: Request, res: Response): void {
  const secure = process.env.NODE_ENV === "production" ||
    req.get("x-forwarded-proto")?.split(",")[0].trim() === "https";
  res.setHeader(
    "Set-Cookie",
    `${COOKIE_NAME}=; Path=/api; HttpOnly; SameSite=Strict; Max-Age=0${secure ? "; Secure" : ""}`,
  );
  res.appendHeader(
    "Set-Cookie",
    `${COOKIE_NAME}=; Path=/api/portal; HttpOnly; SameSite=Strict; Max-Age=0${secure ? "; Secure" : ""}`,
  );
  res.setHeader("Cache-Control", "no-store");
}

export async function requirePortalSession(
  req: Request,
  res: Response,
  next: NextFunction,
): Promise<void> {
  const token = readCookie(req.headers.cookie);
  if (!token || token.length > 256) {
    res.status(401).json({ error: "Sign in to continue." });
    return;
  }
  const tokenHash = hashSessionToken(token);
  const result = await pool.query(
    `SELECT u.id, u.email, u.display_name, u.must_change_password,
            CASE WHEN u.role IN ('admin','owner') THEN 'owner'
                 WHEN u.role='manager' OR mr.staff_id IS NOT NULL THEN 'manager'
                 ELSE 'agent' END AS effective_role
       FROM ${supportSchema}.portal_sessions s
       JOIN ${supportSchema}.portal_users u ON u.id = s.staff_id
       LEFT JOIN ${supportSchema}.portal_manager_roles mr ON mr.staff_id=u.id
      WHERE s.token_hash = $1 AND s.expires > $2 AND u.active = TRUE`,
    [tokenHash, new Date().toISOString()],
  );
  const row = result.rows[0];
  if (!row) {
    clearPortalSessionCookie(req, res);
    res.status(401).json({ error: "Your session has expired. Please sign in again." });
    return;
  }
  req.portalIdentity = {
    id: String(row.id),
    email: String(row.email),
    displayName: String(row.display_name),
    role: row.effective_role as PortalRole,
    mustChangePassword: Boolean(row.must_change_password),
  };
  req.portalSessionHash = tokenHash;
  // Move sessions created by the older /api/portal cookie scope to /api so
  // the same authenticated staff session is available to the shared support API.
  setPortalSessionCookie(req, res, token);
  res.setHeader("Cache-Control", "no-store");
  next();
}

export function requireSameOrigin(req: Request, res: Response, next: NextFunction): void {
  const origin = req.get("origin");
  const host = req.get("host");
  let matches = false;
  if (origin && host) {
    try {
      matches = new URL(origin).host.toLowerCase() === host.toLowerCase();
    } catch {
      matches = false;
    }
  }
  if (!matches) {
    res.status(403).json({ error: "The request could not be verified. Refresh the portal and try again." });
    return;
  }
  next();
}

export function requirePasswordReady(req: Request, res: Response, next: NextFunction): void {
  const routePath = `${req.baseUrl}${req.path}`;
  if (
    req.portalIdentity?.mustChangePassword
    && !isAllowedDuringPasswordSetup(req.method, routePath)
  ) {
    res.status(403).json({ error: "Change your temporary password before continuing." });
    return;
  }
  next();
}

export function toPortalSession(identity: PortalIdentity) {
  return {
    accountType: "staff" as const,
    staffId: identity.id,
    email: identity.email,
    displayName: identity.displayName,
    role: identity.role,
    mustChangePassword: identity.mustChangePassword,
    dashboardPath: portalDashboardPath(identity.role),
  };
}
