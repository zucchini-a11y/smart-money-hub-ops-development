export type LearningProgress = "not_started" | "in_progress" | "completed";

export type MemberLearningRow = Record<string, unknown>;

function timestamp(value: unknown): string | null {
  if (value == null) return null;
  const parsed = new Date(value as string | Date);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

export function buildMemberLearningResponse(rows: MemberLearningRow[]) {
  let allEarlierLessonsCompleted = true;
  const lessons = rows.map((row) => {
    const progressValue = String(row.progress ?? "not_started");
    const progress: LearningProgress = progressValue === "completed" || progressValue === "in_progress"
      ? progressValue
      : "not_started";
    const locked = !allEarlierLessonsCompleted;
    const lesson = {
      lessonId: String(row.lesson_key),
      title: String(row.title),
      summary: String(row.summary),
      bodyMarkdown: locked ? "" : String(row.body_markdown),
      sequence: Number(row.sequence),
      progress,
      locked,
      startedAt: timestamp(row.started_at),
      completedAt: timestamp(row.completed_at),
    };
    if (progress !== "completed") allEarlierLessonsCompleted = false;
    return lesson;
  });

  const completedCount = lessons.filter((lesson) => lesson.progress === "completed").length;
  const totalCount = lessons.length;
  const nextLessonId = lessons.find((lesson) => lesson.progress !== "completed")?.lessonId ?? null;

  return {
    lessons,
    completedCount,
    totalCount,
    completionPercent: totalCount === 0 ? 0 : Math.round((completedCount / totalCount) * 100),
    nextLessonId,
  };
}
