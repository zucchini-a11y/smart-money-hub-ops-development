import { randomUUID } from "node:crypto";
import { pool } from "@workspace/db";
import { logger } from "./logger";
import { buildLearningReminderCandidate } from "./member-notification-policy";
import { resolvePortalSupportSchema } from "./portal-support-schema";

const REMINDER_CYCLE_INTERVAL_MS = 60_000;

function isDevelopmentReminderWorkerEnabled(): boolean {
  if (process.env.NODE_ENV !== "development") return false;
  try {
    return resolvePortalSupportSchema(
      process.env.NODE_ENV,
      process.env.PORTAL_SUPPORT_SCHEMA,
    ) === "smh_test";
  } catch {
    return false;
  }
}

export async function runDevelopmentMemberReminderCycle(): Promise<number> {
  if (!isDevelopmentReminderWorkerEnabled()) return 0;

  const due = await pool.query(
    `SELECT preferences.clerk_user_id,
            TO_CHAR(
              (NOW() AT TIME ZONE preferences.timezone)::date,
              'YYYY-MM-DD'
            ) AS local_date,
            next_lesson.title AS next_lesson_title
       FROM smh_test.member_notification_preferences AS preferences
       JOIN LATERAL (
         SELECT lesson.title
           FROM smh_test.member_learning_lessons AS lesson
           LEFT JOIN smh_test.member_learning_progress AS progress
             ON progress.lesson_key=lesson.lesson_key
            AND progress.clerk_user_id=preferences.clerk_user_id
          WHERE lesson.published=TRUE
            AND COALESCE(progress.progress, 'not_started') <> 'completed'
          ORDER BY lesson.sequence ASC
          LIMIT 1
       ) AS next_lesson ON TRUE
      WHERE preferences.learning_reminders_enabled=TRUE
        AND EXTRACT(
              DOW FROM (NOW() AT TIME ZONE preferences.timezone)
            )::int=preferences.reminder_day_of_week
        AND (NOW() AT TIME ZONE preferences.timezone)::time
              >= preferences.reminder_local_time
        AND EXISTS (
          SELECT 1
            FROM pg_timezone_names AS known_zone
           WHERE known_zone.name=preferences.timezone
        )`,
  );

  let created = 0;
  for (const row of due.rows) {
    const candidate = buildLearningReminderCandidate({
      notificationId: randomUUID(),
      localDate: String(row.local_date ?? ""),
      nextLessonTitle: String(row.next_lesson_title ?? ""),
    });
    if (!candidate) continue;

    const result = await pool.query(
      `INSERT INTO smh_test.member_notifications
         (notification_id, clerk_user_id, idempotency_key, kind, title, message, target_path)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (clerk_user_id, idempotency_key) DO NOTHING
       RETURNING notification_id`,
      [
        candidate.notificationId,
        String(row.clerk_user_id),
        candidate.idempotencyKey,
        candidate.kind,
        candidate.title,
        candidate.message,
        candidate.targetPath,
      ],
    );
    created += result.rowCount ?? 0;
  }
  return created;
}

export function startDevelopmentMemberReminderWorker(): void {
  if (!isDevelopmentReminderWorkerEnabled()) return;

  let cycleInProgress = false;
  const run = async () => {
    if (cycleInProgress) return;
    cycleInProgress = true;
    try {
      const created = await runDevelopmentMemberReminderCycle();
      if (created > 0) {
        logger.info({ created }, "Development learning reminders created");
      }
    } catch (error) {
      logger.error(
        { error: error instanceof Error ? error.message : "unknown error" },
        "Development learning reminder cycle failed",
      );
    } finally {
      cycleInProgress = false;
    }
  };

  void run();
  const timer = setInterval(() => void run(), REMINDER_CYCLE_INTERVAL_MS);
  timer.unref();
}
