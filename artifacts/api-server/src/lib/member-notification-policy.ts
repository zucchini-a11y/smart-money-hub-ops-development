export const defaultMemberNotificationPreferences = {
  learningRemindersEnabled: false,
  reminderDayOfWeek: 1,
  reminderLocalTime: "18:00",
  timezone: "UTC",
  updatedAt: null,
} as const;

export function isValidMemberTimezone(timezone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: timezone });
    return true;
  } catch {
    return false;
  }
}

export function formatMemberReminderTime(value: unknown): string {
  if (typeof value !== "string") return defaultMemberNotificationPreferences.reminderLocalTime;
  const match = /^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d(?:\.\d+)?)?$/.exec(value);
  return match ? `${match[1]}:${match[2]}` : defaultMemberNotificationPreferences.reminderLocalTime;
}

export type LearningReminderCandidate = {
  notificationId: string;
  idempotencyKey: string;
  kind: "learning_reminder";
  title: string;
  message: string;
  targetPath: "/member/learning";
};

export function buildLearningReminderCandidate(input: {
  notificationId: string;
  localDate: string;
  nextLessonTitle: string;
}): LearningReminderCandidate | null {
  const lessonTitle = input.nextLessonTitle.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.localDate) || !lessonTitle) return null;
  return {
    notificationId: input.notificationId,
    idempotencyKey: `learning-reminder:${input.localDate}`,
    kind: "learning_reminder",
    title: "Your weekly learning reminder",
    message: `Continue with “${lessonTitle}” when you are ready. Your saved progress is waiting for you.`,
    targetPath: "/member/learning",
  };
}
