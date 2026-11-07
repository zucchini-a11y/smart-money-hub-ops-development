import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { Router, type IRouter, type Response } from "express";
import {
  GetMemberLearningResponse,
  UpdateMemberLearningProgressBody,
  UpdateMemberLearningProgressResponse,
} from "@workspace/api-zod";
import { pool } from "@workspace/db";
import { buildMemberLearningResponse } from "../lib/member-learning-policy";
import { requireSameOrigin } from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";
import { requireMemberIdentity } from "./member";

const router: IRouter = Router();
const schema = resolvePortalSupportSchema(
  process.env.NODE_ENV,
  process.env.PORTAL_SUPPORT_SCHEMA,
);
const LESSON_ID_RE = /^[a-z0-9-]{1,80}$/;
const GUIDE_FIGURE_IDS_BY_LESSON: Record<string, readonly string[]> = {
  "candle-anatomy": ["candle-anatomy"],
  "swing-high-low": ["swing-high-low"],
  "market-structure": ["market-structure"],
  "bos-and-choch": ["bos"],
  "change-of-character": ["choch"],
  "mss-displacement": ["mss-displacement"],
  "liquidity-and-equal-highs-lows": ["liquidity-equal-highs-lows"],
  "liquidity-sweep": ["liquidity-sweep"],
  inducement: ["inducement"],
  "fair-value-gaps": ["fair-value-gap"],
  "inverse-fvg": ["inverse-fvg"],
  "volume-imbalance-liquidity-void": ["volume-imbalance-liquidity-void"],
  "order-blocks-in-context": ["order-block"],
  "breaker-block": ["breaker-block"],
  "mitigation-block": ["mitigation-block"],
  "rejection-block": ["rejection-block"],
  "premium-discount-ote": ["premium-discount-ote"],
  "power-of-three-judas-swing": ["power-of-three-judas-swing"],
  "multi-timeframe-context": ["premium-discount-ote", "complete-smc-model"],
  "complete-smc-trade-model": ["complete-smc-model"],
  "confirmation-and-risk-planning": ["complete-smc-model"],
};

function developmentLearningEnabled(res: Response): boolean {
  if (process.env.NODE_ENV === "production" || schema !== "smh_test") {
    res.status(404).json({ error: "The member learning center is not enabled in this environment." });
    return false;
  }
  return true;
}

function privateResponse(res: Response): void {
  res.setHeader("Cache-Control", "no-store, private");
  res.setHeader("Pragma", "no-cache");
  res.setHeader("X-Content-Type-Options", "nosniff");
}

async function readMemberLearning(clerkUserId: string) {
  const result = await pool.query(
    `SELECT lesson.lesson_key, lesson.title, lesson.summary, lesson.body_markdown,
            lesson.sequence, progress.progress, progress.started_at, progress.completed_at
       FROM ${schema}.member_learning_lessons AS lesson
       LEFT JOIN ${schema}.member_learning_progress AS progress
         ON progress.lesson_key=lesson.lesson_key
        AND progress.clerk_user_id=$1
      WHERE lesson.published=TRUE
      ORDER BY lesson.sequence ASC`,
    [clerkUserId],
  );
  return GetMemberLearningResponse.parse(
    buildMemberLearningResponse(result.rows as Array<Record<string, unknown>>),
  );
}

router.get("/member/learning", async (req, res): Promise<void> => {
  privateResponse(res);
  if (!developmentLearningEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  const learning = await readMemberLearning(identity.clerkUserId);
  res.json(learning);
});

router.get(
  "/member/learning/:lessonId/figures/:figureId",
  async (req, res): Promise<void> => {
    privateResponse(res);
    if (!developmentLearningEnabled(res)) return;
    const identity = await requireMemberIdentity(req, res);
    if (!identity) return;

    const lessonId = Array.isArray(req.params.lessonId) ? req.params.lessonId[0] : req.params.lessonId;
    const figureId = Array.isArray(req.params.figureId) ? req.params.figureId[0] : req.params.figureId;
    if (
      !lessonId || !LESSON_ID_RE.test(lessonId)
      || !figureId || !LESSON_ID_RE.test(figureId)
      || !GUIDE_FIGURE_IDS_BY_LESSON[lessonId]?.includes(figureId)
    ) {
      res.status(404).json({ error: "This lesson figure is not available." });
      return;
    }

    const unlocked = await pool.query(
      `SELECT lesson.lesson_key
         FROM ${schema}.member_learning_lessons AS lesson
        WHERE lesson.lesson_key=$1
          AND lesson.published=TRUE
          AND NOT EXISTS (
            SELECT 1
              FROM ${schema}.member_learning_lessons AS earlier
              LEFT JOIN ${schema}.member_learning_progress AS earlier_progress
                ON earlier_progress.lesson_key=earlier.lesson_key
               AND earlier_progress.clerk_user_id=$2
             WHERE earlier.published=TRUE
               AND earlier.sequence < lesson.sequence
               AND COALESCE(earlier_progress.progress, 'not_started') <> 'completed'
          )
        LIMIT 1`,
      [lessonId, identity.clerkUserId],
    );
    if (!unlocked.rows.length) {
      res.status(404).json({ error: "This lesson figure is not available." });
      return;
    }

    const image = await readFile(
      resolve(process.cwd(), "assets", "academy-guide", `${figureId}.webp`),
    ).catch(() => null);
    if (!image) {
      res.status(404).json({ error: "This lesson figure is not available." });
      return;
    }

    res.type("image/webp").status(200).send(image);
  },
);

router.patch(
  "/member/learning/:lessonId/progress",
  requireSameOrigin,
  async (req, res): Promise<void> => {
    privateResponse(res);
    if (!developmentLearningEnabled(res)) return;
    const identity = await requireMemberIdentity(req, res);
    if (!identity) return;

    const lessonId = Array.isArray(req.params.lessonId)
      ? req.params.lessonId[0]
      : req.params.lessonId;
    if (!lessonId || !LESSON_ID_RE.test(lessonId)) {
      res.status(400).json({ error: "A valid lesson identifier is required." });
      return;
    }

    const parsed = UpdateMemberLearningProgressBody.safeParse(req.body);
    if (!parsed.success) {
      res.status(400).json({ error: "Choose a valid lesson progress state." });
      return;
    }

    const completedAt = parsed.data.progress === "completed" ? "NOW()" : "NULL";
    const result = await pool.query(
      `INSERT INTO ${schema}.member_learning_progress AS existing
         (clerk_user_id, lesson_key, progress, started_at, completed_at, updated_at)
       SELECT $1, lesson.lesson_key, $3, NOW(), ${completedAt}, NOW()
         FROM ${schema}.member_learning_lessons AS lesson
        WHERE lesson.lesson_key=$2 AND lesson.published=TRUE
          AND NOT EXISTS (
            SELECT 1
              FROM ${schema}.member_learning_lessons AS earlier
              LEFT JOIN ${schema}.member_learning_progress AS earlier_progress
                ON earlier_progress.lesson_key=earlier.lesson_key
               AND earlier_progress.clerk_user_id=$1
             WHERE earlier.published=TRUE
               AND earlier.sequence < lesson.sequence
               AND COALESCE(earlier_progress.progress, 'not_started') <> 'completed'
          )
       ON CONFLICT (clerk_user_id, lesson_key) DO UPDATE
          SET progress=CASE
                WHEN existing.progress='completed'
                  THEN 'completed'
                ELSE EXCLUDED.progress
              END,
              started_at=COALESCE(existing.started_at, NOW()),
              completed_at=COALESCE(
                existing.completed_at,
                EXCLUDED.completed_at
              ),
              updated_at=NOW()
       RETURNING lesson_key`,
      [identity.clerkUserId, lessonId, parsed.data.progress],
    );
    if (!result.rows.length) {
      res.status(404).json({ error: "That lesson is not available." });
      return;
    }

    const learning = await readMemberLearning(identity.clerkUserId);
    res.json(UpdateMemberLearningProgressResponse.parse({ learning }));
  },
);

export default router;
