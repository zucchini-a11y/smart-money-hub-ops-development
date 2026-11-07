import test from "node:test";
import assert from "node:assert/strict";
import { buildMemberLearningResponse } from "../src/lib/member-learning-policy.ts";

const lessons = [
  { lesson_key: "orientation", title: "Orientation", summary: "Start here", body_markdown: "Orientation content", sequence: 1 },
  { lesson_key: "market-structure", title: "Market Structure", summary: "Study structure", body_markdown: "Market structure content", sequence: 2 },
  { lesson_key: "bos-and-choch", title: "BOS and CHoCH", summary: "Study breaks", body_markdown: "BOS content", sequence: 3 },
];

test("locked lessons do not return their content before earlier lessons are complete", () => {
  const response = buildMemberLearningResponse(lessons);
  assert.equal(response.lessons[0].locked, false);
  assert.equal(response.lessons[0].bodyMarkdown, "Orientation content");
  assert.equal(response.lessons[1].locked, true);
  assert.equal(response.lessons[1].bodyMarkdown, "");
  assert.equal(response.lessons[2].locked, true);
  assert.equal(response.lessons[2].bodyMarkdown, "");
  assert.equal(response.nextLessonId, "orientation");
});

test("completing a lesson unlocks only the next published lesson", () => {
  const response = buildMemberLearningResponse([
    { ...lessons[0], progress: "completed", started_at: "2026-11-07T09:00:00Z", completed_at: "2026-11-07T09:10:00Z" },
    lessons[1],
    lessons[2],
  ]);
  assert.equal(response.completedCount, 1);
  assert.equal(response.totalCount, 3);
  assert.equal(response.completionPercent, 33);
  assert.equal(response.lessons[0].locked, false);
  assert.equal(response.lessons[1].locked, false);
  assert.equal(response.lessons[1].bodyMarkdown, "Market structure content");
  assert.equal(response.lessons[2].locked, true);
  assert.equal(response.nextLessonId, "market-structure");
});

test("an in-progress lesson does not unlock the following lesson", () => {
  const response = buildMemberLearningResponse([
    { ...lessons[0], progress: "completed" },
    { ...lessons[1], progress: "in_progress" },
    lessons[2],
  ]);
  assert.equal(response.lessons[1].locked, false);
  assert.equal(response.lessons[1].bodyMarkdown, "Market structure content");
  assert.equal(response.lessons[2].locked, true);
  assert.equal(response.lessons[2].bodyMarkdown, "");
  assert.equal(response.nextLessonId, "market-structure");
});

test("empty learning data produces no fabricated progress", () => {
  assert.deepEqual(buildMemberLearningResponse([]), {
    lessons: [],
    completedCount: 0,
    totalCount: 0,
    completionPercent: 0,
    nextLessonId: null,
  });
});
