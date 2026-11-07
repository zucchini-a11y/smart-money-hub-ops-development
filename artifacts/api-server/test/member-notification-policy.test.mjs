import test from "node:test";
import assert from "node:assert/strict";
import {
  buildLearningReminderCandidate,
  defaultMemberNotificationPreferences,
  formatMemberReminderTime,
  isValidMemberTimezone,
} from "../src/lib/member-notification-policy.ts";

test("learning reminders default to opt-in off with a safe weekly schedule", () => {
  assert.deepEqual(defaultMemberNotificationPreferences, {
    learningRemindersEnabled: false,
    reminderDayOfWeek: 1,
    reminderLocalTime: "18:00",
    timezone: "UTC",
    updatedAt: null,
  });
});

test("timezone validation accepts IANA zones and rejects arbitrary values", () => {
  assert.equal(isValidMemberTimezone("Africa/Lagos"), true);
  assert.equal(isValidMemberTimezone("UTC"), true);
  assert.equal(isValidMemberTimezone("not/a-timezone"), false);
});

test("database time values are returned as a 24-hour HH:mm setting", () => {
  assert.equal(formatMemberReminderTime("18:45:00"), "18:45");
  assert.equal(formatMemberReminderTime("07:05"), "07:05");
  assert.equal(formatMemberReminderTime("25:99:00"), "18:00");
});

test("weekly reminder records contain a stable per-local-date idempotency key", () => {
  const input = {
    notificationId: "d94b1108-b8a7-43d3-8aeb-9c937d150739",
    localDate: "2026-11-09",
    nextLessonTitle: "Understanding market structure",
  };
  const reminder = buildLearningReminderCandidate(input);
  assert.deepEqual(reminder, {
    notificationId: input.notificationId,
    idempotencyKey: "learning-reminder:2026-11-09",
    kind: "learning_reminder",
    title: "Your weekly learning reminder",
    message: "Continue with “Understanding market structure” when you are ready. Your saved progress is waiting for you.",
    targetPath: "/member/learning",
  });
  assert.equal(buildLearningReminderCandidate(input)?.idempotencyKey, reminder?.idempotencyKey);
});

test("a reminder is not created with an invalid local date or empty lesson title", () => {
  assert.equal(buildLearningReminderCandidate({
    notificationId: "d94b1108-b8a7-43d3-8aeb-9c937d150739",
    localDate: "today",
    nextLessonTitle: "Lesson",
  }), null);
  assert.equal(buildLearningReminderCandidate({
    notificationId: "d94b1108-b8a7-43d3-8aeb-9c937d150739",
    localDate: "2026-11-09",
    nextLessonTitle: "   ",
  }), null);
});
