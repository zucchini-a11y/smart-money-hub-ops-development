import { Router, type IRouter, type Response } from "express";
import {
  GetMemberNotificationsResponse,
  MarkAllMemberNotificationsReadResponse,
  MarkMemberNotificationReadParams,
  MarkMemberNotificationReadResponse,
  UpdateMemberNotificationPreferencesBody,
  UpdateMemberNotificationPreferencesResponse,
} from "@workspace/api-zod";
import { pool } from "@workspace/db";
import {
  defaultMemberNotificationPreferences,
  formatMemberReminderTime,
  isValidMemberTimezone,
} from "../lib/member-notification-policy";
import { requireSameOrigin } from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";
import { requireMemberIdentity } from "./member";

const router: IRouter = Router();
const schema = resolvePortalSupportSchema(
  process.env.NODE_ENV,
  process.env.PORTAL_SUPPORT_SCHEMA,
);

function developmentNotificationsEnabled(res: Response): boolean {
  if (process.env.NODE_ENV === "production" || schema !== "smh_test") {
    res.status(404).json({ error: "Member notifications are not enabled in this environment." });
    return false;
  }
  return true;
}

function privateResponse(res: Response): void {
  res.setHeader("Cache-Control", "no-store, private");
  res.setHeader("Pragma", "no-cache");
}

function preferencesFromRow(row?: Record<string, unknown>) {
  if (!row) return defaultMemberNotificationPreferences;
  return {
    learningRemindersEnabled: row.learning_reminders_enabled === true,
    reminderDayOfWeek: Number(row.reminder_day_of_week ?? 1),
    reminderLocalTime: formatMemberReminderTime(row.reminder_local_time),
    timezone: String(row.timezone ?? "UTC"),
    updatedAt: row.updated_at ?? null,
  };
}

async function countUnread(clerkUserId: string): Promise<number> {
  const result = await pool.query(
    `SELECT COUNT(*)::int AS unread_count
       FROM ${schema}.member_notifications
      WHERE clerk_user_id=$1 AND read_at IS NULL`,
    [clerkUserId],
  );
  return Number(result.rows[0]?.unread_count ?? 0);
}

router.get("/member/notifications", async (req, res): Promise<void> => {
  privateResponse(res);
  if (!developmentNotificationsEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;

  const [notificationResult, preferenceResult, unreadCount] = await Promise.all([
    pool.query(
      `SELECT notification_id, kind, title, message, target_path, created_at, read_at
         FROM ${schema}.member_notifications
        WHERE clerk_user_id=$1
        ORDER BY created_at DESC
        LIMIT 50`,
      [identity.clerkUserId],
    ),
    pool.query(
      `SELECT learning_reminders_enabled, reminder_day_of_week,
              reminder_local_time, timezone, updated_at
         FROM ${schema}.member_notification_preferences
        WHERE clerk_user_id=$1`,
      [identity.clerkUserId],
    ),
    countUnread(identity.clerkUserId),
  ]);

  res.json(GetMemberNotificationsResponse.parse({
    notifications: notificationResult.rows.map((row) => ({
      notificationId: String(row.notification_id),
      kind: row.kind,
      title: String(row.title),
      message: String(row.message),
      targetPath: row.target_path,
      createdAt: row.created_at,
      readAt: row.read_at ?? null,
    })),
    unreadCount,
    preferences: preferencesFromRow(preferenceResult.rows[0]),
  }));
});

router.post(
  "/member/notifications/:notificationId/read",
  requireSameOrigin,
  async (req, res): Promise<void> => {
    privateResponse(res);
    if (!developmentNotificationsEnabled(res)) return;
    const identity = await requireMemberIdentity(req, res);
    if (!identity) return;

    const parsedParams = MarkMemberNotificationReadParams.safeParse(req.params);
    if (!parsedParams.success) {
      res.status(400).json({ error: "A valid notification identifier is required." });
      return;
    }

    const result = await pool.query(
      `UPDATE ${schema}.member_notifications
          SET read_at=COALESCE(read_at, NOW())
        WHERE notification_id=$1 AND clerk_user_id=$2
        RETURNING notification_id`,
      [parsedParams.data.notificationId, identity.clerkUserId],
    );
    if (!result.rows.length) {
      res.status(404).json({ error: "Notification not found." });
      return;
    }

    res.json(MarkMemberNotificationReadResponse.parse({
      unreadCount: await countUnread(identity.clerkUserId),
    }));
  },
);

router.post(
  "/member/notifications/read-all",
  requireSameOrigin,
  async (req, res): Promise<void> => {
    privateResponse(res);
    if (!developmentNotificationsEnabled(res)) return;
    const identity = await requireMemberIdentity(req, res);
    if (!identity) return;

    await pool.query(
      `UPDATE ${schema}.member_notifications
          SET read_at=NOW()
        WHERE clerk_user_id=$1 AND read_at IS NULL`,
      [identity.clerkUserId],
    );
    res.json(MarkAllMemberNotificationsReadResponse.parse({
      unreadCount: await countUnread(identity.clerkUserId),
    }));
  },
);

router.patch(
  "/member/notification-preferences",
  requireSameOrigin,
  async (req, res): Promise<void> => {
    privateResponse(res);
    if (!developmentNotificationsEnabled(res)) return;
    const identity = await requireMemberIdentity(req, res);
    if (!identity) return;

    const parsed = UpdateMemberNotificationPreferencesBody.safeParse(req.body);
    if (!parsed.success || !isValidMemberTimezone(parsed.data.timezone)) {
      res.status(400).json({ error: "Choose a valid reminder day, time, and timezone." });
      return;
    }

    const result = await pool.query(
      `INSERT INTO ${schema}.member_notification_preferences
         (clerk_user_id, learning_reminders_enabled, reminder_day_of_week,
          reminder_local_time, timezone, updated_at)
       VALUES ($1, $2, $3, $4::time, $5, NOW())
       ON CONFLICT (clerk_user_id) DO UPDATE
         SET learning_reminders_enabled=EXCLUDED.learning_reminders_enabled,
             reminder_day_of_week=EXCLUDED.reminder_day_of_week,
             reminder_local_time=EXCLUDED.reminder_local_time,
             timezone=EXCLUDED.timezone,
             updated_at=NOW()
       RETURNING learning_reminders_enabled, reminder_day_of_week,
                 reminder_local_time, timezone, updated_at`,
      [
        identity.clerkUserId,
        parsed.data.learningRemindersEnabled,
        parsed.data.reminderDayOfWeek,
        parsed.data.reminderLocalTime,
        parsed.data.timezone,
      ],
    );

    res.json(UpdateMemberNotificationPreferencesResponse.parse({
      preferences: preferencesFromRow(result.rows[0]),
    }));
  },
);

export default router;
