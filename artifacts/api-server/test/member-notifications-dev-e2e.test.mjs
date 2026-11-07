import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { pool } from "@workspace/db";
import { runDevelopmentMemberReminderCycle } from "../src/lib/development-member-reminders.ts";

test("Development reminder cycle creates one private notification per weekly schedule", async (context) => {
  if (process.env.RUN_DEVELOPMENT_NOTIFICATION_E2E !== "true") {
    context.skip("Set RUN_DEVELOPMENT_NOTIFICATION_E2E=true to use temporary smh_test data.");
    return;
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error("Refusing to run Development reminder test in Production.");
  }

  const testClerkUserId = `dev-reminder-test-${randomUUID()}`;
  try {
    const lessons = await pool.query(
      "SELECT COUNT(*)::int AS count FROM smh_test.member_learning_lessons WHERE published=TRUE",
    );
    assert.ok(Number(lessons.rows[0]?.count) > 0, "A published Development lesson is required.");

    await pool.query(
      `INSERT INTO smh_test.member_notification_preferences
         (clerk_user_id, learning_reminders_enabled, reminder_day_of_week,
          reminder_local_time, timezone)
       VALUES (
         $1,
         TRUE,
         EXTRACT(DOW FROM (NOW() AT TIME ZONE 'UTC'))::smallint,
         TIME '00:00',
         'UTC'
       )`,
      [testClerkUserId],
    );

    await runDevelopmentMemberReminderCycle();
    const first = await pool.query(
      `SELECT COUNT(*)::int AS count
         FROM smh_test.member_notifications
        WHERE clerk_user_id=$1
          AND kind='learning_reminder'`,
      [testClerkUserId],
    );
    assert.equal(Number(first.rows[0]?.count), 1);

    await runDevelopmentMemberReminderCycle();
    const second = await pool.query(
      `SELECT COUNT(*)::int AS count
         FROM smh_test.member_notifications
        WHERE clerk_user_id=$1
          AND kind='learning_reminder'`,
      [testClerkUserId],
    );
    assert.equal(Number(second.rows[0]?.count), 1, "A second cycle must not create a duplicate.");
  } finally {
    await pool.query(
      "DELETE FROM smh_test.member_notifications WHERE clerk_user_id=$1",
      [testClerkUserId],
    );
    await pool.query(
      "DELETE FROM smh_test.member_notification_preferences WHERE clerk_user_id=$1",
      [testClerkUserId],
    );
    await pool.end();
  }
});
