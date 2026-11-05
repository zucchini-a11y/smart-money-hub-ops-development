import { randomUUID } from "node:crypto";
import path from "node:path";
import { Router, type IRouter, type NextFunction, type Request, type Response } from "express";
import { pool } from "@workspace/db";
import {
  CreateEducationVideoDraftBody,
  CreateEducationVideoDraftResponse,
  ListEducationVideosResponse,
} from "@workspace/api-zod";
import { requirePasswordReady, requirePortalSession, requireSameOrigin } from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";
import {
  getEducationVideoDestination,
  mayManageEducationVideos,
  validEducationVideoMetadata,
} from "../lib/education-video-policy";

const router: IRouter = Router();
const supportSchema = resolvePortalSupportSchema(
  process.env.NODE_ENV,
  process.env.PORTAL_SUPPORT_SCHEMA,
);
// Persistent video storage has not been provisioned. Never fall back to local disk.
const videoStorageAvailable = false;

router.use("/portal", (_req, res, next) => {
  res.setHeader("Cache-Control", "no-store");
  next();
}, requirePortalSession, requirePasswordReady);

function ownerOnly(req: Request, res: Response): boolean {
  if (mayManageEducationVideos(req.portalIdentity?.role)) return true;
  res.status(403).json({ error: "Only the owner can manage educational videos." });
  return false;
}

function destination() {
  return getEducationVideoDestination(process.env, supportSchema);
}

function targetLabel(): string {
  return `Educational Group · ${destination().topicName}`;
}

function publicVideo(row: Record<string, unknown>) {
  return {
    videoId: String(row.id),
    title: String(row.title),
    caption: String(row.caption),
    fileName: String(row.file_name),
    byteSize: Number(row.byte_size),
    status: String(row.status),
    createdAt: String(row.created),
    publishedAt: row.published_at ? String(row.published_at) : null,
    targetLabel: targetLabel(),
  };
}

async function addAudit(actorId: string, action: string, entityId: string, detail: string) {
  await pool.query(
    `INSERT INTO ${supportSchema}.portal_audit
      (id,actor_id,action,entity_id,created,detail) VALUES($1,$2,$3,$4,$5,$6)`,
    [randomUUID().replaceAll("-", ""), actorId, action, entityId, new Date().toISOString(), detail],
  );
}

function safeFileName(value: string): string {
  return path.basename(value.replaceAll("\\", "/")).replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 160);
}

router.get("/portal/education-videos", async (req, res): Promise<void> => {
  if (!ownerOnly(req, res)) return;
  const result = await pool.query(
    `SELECT id,title,caption,file_name,byte_size,status,created,published_at
       FROM ${supportSchema}.education_video_posts
      ORDER BY created DESC,id DESC LIMIT 100`,
  );
  const target = destination();
  const label = `Educational Group · ${target.topicName}`;
  const notice = !target.available
    ? "The Video tutorials topic must be distinct from the Education lesson/announcement topics and from PRO Signals and Market Analysis. Uploads can be saved as drafts."
    : !target.publishingEnabled
      ? "Video publishing is locked. Drafts can be prepared, but nothing can be sent."
      : "Review the exact video and caption before choosing Publish.";
  res.json(ListEducationVideosResponse.parse({
    videos: result.rows.map(publicVideo),
    targetAvailable: target.available,
    targetLabel: label,
    publishingEnabled: target.available && target.publishingEnabled,
    notice,
  }));
});

router.post("/portal/education-videos", requireSameOrigin, async (req, res): Promise<void> => {
  if (!ownerOnly(req, res)) return;
  if (!videoStorageAvailable) {
    res.status(503).json({ error: "Persistent video storage is not available. No draft or file was saved." });
    return;
  }
  const parsed = CreateEducationVideoDraftBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Enter a title, caption, and MP4 file within the size limit." });
    return;
  }
  const data = { ...parsed.data, fileName: safeFileName(parsed.data.fileName) };
  if (!validEducationVideoMetadata(data)) {
    res.status(400).json({ error: "The file must be an MP4 under 50 MB, with a short title and caption." });
    return;
  }
  const duplicate = await pool.query(
    `SELECT * FROM ${supportSchema}.education_video_posts WHERE request_id=$1`,
    [data.requestId],
  );
  if (duplicate.rows[0]) {
    res.json(CreateEducationVideoDraftResponse.parse(publicVideo(duplicate.rows[0])));
    return;
  }
  const videoId = randomUUID().replaceAll("-", "");
  const storageName = `${videoId}.mp4`;
  const stamp = new Date().toISOString();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const inserted = await client.query(
      `INSERT INTO ${supportSchema}.education_video_posts
        (id,title,caption,file_name,storage_name,byte_size,status,created_by,created_by_name,
         request_id,target_topic_name,created,updated)
       VALUES($1,$2,$3,$4,$5,$6,'awaiting_upload',$7,$8,$9,$10,$11,$11)
       RETURNING id,title,caption,file_name,byte_size,status,created,published_at`,
      [videoId, data.title.trim(), data.caption.trim(), data.fileName, storageName,
        data.byteSize, req.portalIdentity!.id, req.portalIdentity!.displayName,
        data.requestId, destination().topicName, stamp],
    );
    await client.query(
      `INSERT INTO ${supportSchema}.portal_audit
        (id,actor_id,action,entity_id,created,detail) VALUES($1,$2,$3,$4,$5,$6)`,
      [randomUUID().replaceAll("-", ""), req.portalIdentity!.id,
        "education_video_draft_created", videoId, stamp, "Created an educational video draft."],
    );
    await client.query("COMMIT");
    res.status(201).json(CreateEducationVideoDraftResponse.parse(publicVideo(inserted.rows[0])));
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
});

router.put("/portal/education-videos/:videoId/file", requireSameOrigin, (req, res): void => {
  if (!ownerOnly(req, res)) return;
  res.status(503).json({ error: "Persistent video storage is not available. The file was not accepted." });
});

router.get("/portal/education-videos/:videoId/file", (req, res): void => {
  if (!ownerOnly(req, res)) return;
  res.status(503).json({ error: "Persistent video storage is not available. Preview is disabled." });
});

router.post("/portal/education-videos/:videoId/publish", requireSameOrigin, (req, res): void => {
  if (!ownerOnly(req, res)) return;
  res.status(423).json({ error: "Publishing is paused until secure persistent video storage is available. Nothing was sent." });
});

router.use((error: unknown, req: Request, res: Response, _next: NextFunction): void => {
  const status = typeof error === "object" && error !== null && "status" in error
    ? Number((error as { status: unknown }).status) : 0;
  if (status === 413) {
    res.status(413).json({ error: "Video must be no larger than 50 MB." });
    return;
  }
  const errorType = error instanceof Error ? error.name : "UnknownError";
  req.log.error({ errorType }, "Education video request failed");
  if (!res.headersSent) res.status(503).json({ error: "The education video service is temporarily unavailable." });
});

export default router;
