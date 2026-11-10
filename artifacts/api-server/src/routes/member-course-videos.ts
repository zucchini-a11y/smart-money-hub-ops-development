import { createHash, randomUUID } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import { mkdir, rename, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { Router, type IRouter, type Request, type Response } from "express";
import { pool } from "@workspace/db";
import { requirePasswordReady, requirePortalSession, requireSameOrigin } from "../lib/portal-auth";
import { resolvePortalSupportSchema } from "../lib/portal-support-schema";
import { requireMemberIdentity } from "./member";

const router: IRouter = Router();
const schema = resolvePortalSupportSchema(process.env.NODE_ENV, process.env.PORTAL_SUPPORT_SCHEMA);
const MAX_VIDEO_BYTES = 262_144_000;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function privateResponse(res: Response): void {
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("Pragma", "no-cache");
  res.setHeader("X-Content-Type-Options", "nosniff");
}

function featureEnabled(res: Response): boolean {
  const isProduction = process.env.NODE_ENV === "production";
  const expectedSchema = isProduction ? "smh" : "smh_test";
  if (schema !== expectedSchema || (isProduction && process.env.SMH_MEMBER_VIDEOS_ENABLED !== "true")) {
    res.status(404).json({ error: "Member video lessons are not enabled in this environment." });
    return false;
  }
  return true;
}

function storageDirectory(): string | null {
  const configured = process.env.MEMBER_VIDEO_STORAGE_DIR?.trim();
  if (configured) return path.resolve(configured);
  if (process.env.NODE_ENV === "production") return null;
  // Local Development storage is deliberately isolated and temporary.
  return path.join(tmpdir(), "smh-member-course-videos-development");
}

function ownerOnly(req: Request, res: Response): boolean {
  if (req.portalIdentity?.role === "owner") return true;
  res.status(403).json({ error: "Only the owner can manage member video lessons." });
  return false;
}

function safeFileName(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const cleaned = path.basename(value.replaceAll("\\", "/"))
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .trim()
    .slice(0, 180);
  return cleaned.toLowerCase().endsWith(".mp4") ? cleaned : null;
}

function validTitle(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.trim().length <= 140;
}

function validDescription(value: unknown): value is string {
  return value === undefined || (typeof value === "string" && value.length <= 3000);
}

function safeId(value: unknown): value is string {
  return typeof value === "string" && UUID_RE.test(value);
}

function publicVideo(row: Record<string, unknown>) {
  return {
    videoId: String(row.id),
    title: String(row.title),
    description: String(row.description ?? ""),
    fileName: String(row.file_name),
    byteSize: Number(row.byte_size),
    status: String(row.status),
    createdAt: String(row.created_at),
    publishedAt: row.published_at ? String(row.published_at) : null,
  };
}

async function videoRow(id: string) {
  const result = await pool.query(
    `SELECT id,title,description,file_name,storage_name,byte_size,file_sha256,status,
            created_at,published_at
       FROM ${schema}.member_course_videos
      WHERE id=$1`,
    [id],
  );
  return result.rows[0] as Record<string, unknown> | undefined;
}

async function streamProtectedFile(
  req: Request,
  res: Response,
  filePath: string,
  downloadName: string,
): Promise<void> {
  const info = await stat(filePath).catch(() => null);
  if (!info?.isFile()) {
    res.status(404).json({ error: "This video file is not available." });
    return;
  }

  const range = req.get("range");
  let start = 0;
  let end = info.size - 1;
  let status = 200;
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range.trim());
    if (!match || (!match[1] && !match[2])) {
      res.setHeader("Content-Range", `bytes */${info.size}`);
      res.status(416).end();
      return;
    }
    if (!match[1]) {
      const suffix = Number(match[2]);
      if (!Number.isSafeInteger(suffix) || suffix < 1) {
        res.setHeader("Content-Range", `bytes */${info.size}`);
        res.status(416).end();
        return;
      }
      start = Math.max(0, info.size - suffix);
    } else {
      start = Number(match[1]);
      if (match[2]) end = Number(match[2]);
    }
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= info.size) {
      res.setHeader("Content-Range", `bytes */${info.size}`);
      res.status(416).end();
      return;
    }
    end = Math.min(end, info.size - 1);
    status = 206;
    res.setHeader("Content-Range", `bytes ${start}-${end}/${info.size}`);
  }

  privateResponse(res);
  res.setHeader("Accept-Ranges", "bytes");
  res.setHeader("Content-Type", "video/mp4");
  res.setHeader("Content-Disposition", `inline; filename="${downloadName}"`);
  res.setHeader("Content-Length", String(end - start + 1));
  res.status(status);
  const stream = createReadStream(filePath, { start, end });
  stream.on("error", () => {
    if (!res.headersSent) res.status(404).end();
    else res.destroy();
  });
  stream.pipe(res);
}

router.use(
  "/portal/member-course-videos",
  (_req, res, next) => {
    privateResponse(res);
    next();
  },
  requirePortalSession,
  requirePasswordReady,
);

router.get("/portal/member-course-videos", async (req, res): Promise<void> => {
  if (!featureEnabled(res) || !ownerOnly(req, res)) return;
  const result = await pool.query(
    `SELECT id,title,description,file_name,byte_size,status,created_at,published_at
       FROM ${schema}.member_course_videos
      ORDER BY created_at ASC,id ASC`,
  );
  res.json({
    storageAvailable: Boolean(storageDirectory()),
    maxUploadBytes: MAX_VIDEO_BYTES,
    videos: result.rows.map(publicVideo),
  });
});

router.post("/portal/member-course-videos", requireSameOrigin, async (req, res): Promise<void> => {
  if (!featureEnabled(res) || !ownerOnly(req, res)) return;
  if (!storageDirectory()) {
    res.status(503).json({ error: "Set MEMBER_VIDEO_STORAGE_DIR to a persistent Hostinger directory before uploading." });
    return;
  }
  const fileName = safeFileName(req.body?.fileName);
  const byteSize = Number(req.body?.byteSize);
  if (
    !validTitle(req.body?.title)
    || !validDescription(req.body?.description)
    || !fileName
    || !Number.isSafeInteger(byteSize)
    || byteSize < 12
    || byteSize > MAX_VIDEO_BYTES
  ) {
    res.status(400).json({ error: "Provide a title, an MP4 file name, and a file no larger than 250 MB." });
    return;
  }

  const id = randomUUID();
  const result = await pool.query(
    `INSERT INTO ${schema}.member_course_videos
      (id,title,description,file_name,storage_name,byte_size,status,created_by,created_by_name)
     VALUES($1,$2,$3,$4,$5,$6,'awaiting_upload',$7,$8)
     RETURNING id,title,description,file_name,byte_size,status,created_at,published_at`,
    [id, req.body.title.trim(), (req.body.description ?? "").trim(), fileName, `${id}.mp4`,
      byteSize, req.portalIdentity!.id, req.portalIdentity!.displayName],
  );
  res.status(201).json(publicVideo(result.rows[0]));
});

router.put("/portal/member-course-videos/:videoId/file", requireSameOrigin, async (req, res): Promise<void> => {
  if (!featureEnabled(res) || !ownerOnly(req, res)) return;
  const id = req.params.videoId;
  if (!safeId(id)) {
    res.status(404).json({ error: "Video draft not found." });
    return;
  }
  const directory = storageDirectory();
  if (!directory) {
    res.status(503).json({ error: "Persistent video storage is not configured." });
    return;
  }
  const row = await videoRow(id);
  if (!row || row.status !== "awaiting_upload") {
    res.status(404).json({ error: "This draft is not waiting for a file." });
    return;
  }
  const contentType = req.get("content-type")?.split(";")[0].trim().toLowerCase();
  const expectedBytes = Number(req.get("content-length"));
  if (contentType !== "video/mp4" || !Number.isSafeInteger(expectedBytes) || expectedBytes !== Number(row.byte_size)) {
    res.status(400).json({ error: "Upload the selected MP4 file with its original size." });
    return;
  }
  if (expectedBytes > MAX_VIDEO_BYTES) {
    res.status(413).json({ error: "Video files must be 250 MB or smaller." });
    return;
  }

  const targetPath = path.join(directory, `${id}.mp4`);
  const tempPath = `${targetPath}.${randomUUID()}.upload`;
  let received = 0;
  let prefix = Buffer.alloc(0);
  const digest = createHash("sha256");
  const validateStream = new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      received += chunk.length;
      if (received > MAX_VIDEO_BYTES || received > expectedBytes) {
        callback(Object.assign(new Error("Upload size exceeded"), { status: 413 }));
        return;
      }
      if (prefix.length < 12) prefix = Buffer.concat([prefix, chunk.subarray(0, 12 - prefix.length)]);
      digest.update(chunk);
      callback(null, chunk);
    },
  });
  try {
    await mkdir(directory, { recursive: true, mode: 0o750 });
    await pipeline(req, validateStream, createWriteStream(tempPath, { flags: "wx", mode: 0o640 }));
    if (received !== expectedBytes || prefix.toString("ascii", 4, 8) !== "ftyp") {
      await rm(tempPath, { force: true });
      res.status(400).json({ error: "The uploaded file is not a complete MP4 video." });
      return;
    }
    await rename(tempPath, targetPath);
    try {
      const updated = await pool.query(
        `UPDATE ${schema}.member_course_videos
            SET status='draft',byte_size=$2,file_sha256=$3,updated_at=NOW()
          WHERE id=$1 AND status='awaiting_upload'
          RETURNING id,title,description,file_name,byte_size,status,created_at,published_at`,
        [id, received, digest.digest("hex")],
      );
      if (!updated.rows[0]) throw new Error("Video draft changed during upload.");
      res.json(publicVideo(updated.rows[0]));
    } catch (error) {
      await rm(targetPath, { force: true });
      throw error;
    }
  } catch (error) {
    await rm(tempPath, { force: true }).catch(() => undefined);
    if (!res.headersSent && (error as { status?: number })?.status === 413) {
      res.status(413).json({ error: "Video files must be 250 MB or smaller." });
      return;
    }
    if (!res.headersSent) res.status(503).json({ error: "The video upload did not complete. You can retry the draft." });
  }
});

router.get("/portal/member-course-videos/:videoId/file", async (req, res): Promise<void> => {
  if (!featureEnabled(res) || !ownerOnly(req, res)) return;
  const id = req.params.videoId;
  if (!safeId(id)) {
    res.status(404).json({ error: "Video not found." });
    return;
  }
  const row = await videoRow(id);
  const directory = storageDirectory();
  if (!row || row.status === "awaiting_upload" || !directory) {
    res.status(404).json({ error: "Video preview is not available." });
    return;
  }
  await streamProtectedFile(req, res, path.join(directory, `${id}.mp4`), `${id}.mp4`);
});

router.post("/portal/member-course-videos/:videoId/publish", requireSameOrigin, async (req, res): Promise<void> => {
  if (!featureEnabled(res) || !ownerOnly(req, res)) return;
  const id = req.params.videoId;
  const directory = storageDirectory();
  if (!safeId(id) || !directory) {
    res.status(404).json({ error: "Video draft not found." });
    return;
  }
  const row = await videoRow(id);
  if (!row || row.status === "awaiting_upload") {
    res.status(409).json({ error: "Upload and review the video before publishing it." });
    return;
  }
  const file = await stat(path.join(directory, `${id}.mp4`)).catch(() => null);
  if (!file?.isFile()) {
    res.status(409).json({ error: "The video file is missing. It cannot be published." });
    return;
  }
  const result = await pool.query(
    `UPDATE ${schema}.member_course_videos
        SET status='published',published_at=COALESCE(published_at,NOW()),updated_at=NOW()
      WHERE id=$1
      RETURNING id,title,description,file_name,byte_size,status,created_at,published_at`,
    [id],
  );
  res.json(publicVideo(result.rows[0]));
});

router.post("/portal/member-course-videos/:videoId/unpublish", requireSameOrigin, async (req, res): Promise<void> => {
  if (!featureEnabled(res) || !ownerOnly(req, res)) return;
  const id = req.params.videoId;
  if (!safeId(id)) {
    res.status(404).json({ error: "Video not found." });
    return;
  }
  const current = await videoRow(id);
  if (!current || current.status === "awaiting_upload") {
    res.status(409).json({ error: "Complete the upload before unpublishing this video." });
    return;
  }
  const result = await pool.query(
    `UPDATE ${schema}.member_course_videos
        SET status='draft',published_at=NULL,updated_at=NOW()
      WHERE id=$1 AND status <> 'awaiting_upload'
      RETURNING id,title,description,file_name,byte_size,status,created_at,published_at`,
    [id],
  );
  if (!result.rows[0]) {
    res.status(404).json({ error: "Video not found." });
    return;
  }
  res.json(publicVideo(result.rows[0]));
});

router.get("/member/videos", async (req, res): Promise<void> => {
  privateResponse(res);
  if (!featureEnabled(res)) return;
  const identity = await requireMemberIdentity(req, res);
  if (!identity) return;
  if (!storageDirectory()) {
    res.status(503).json({ error: "Video lessons are not available in this environment." });
    return;
  }
  const result = await pool.query(
    `SELECT id,title,description,file_name,byte_size,created_at,published_at
       FROM ${schema}.member_course_videos
      WHERE status='published'
      ORDER BY created_at ASC,id ASC`,
  );
  res.json({
    videos: result.rows.map((row) => ({
      videoId: String(row.id),
      title: String(row.title),
      description: String(row.description ?? ""),
      byteSize: Number(row.byte_size),
      publishedAt: row.published_at ? String(row.published_at) : null,
    })),
  });
});

router.get("/member/videos/:videoId/file", async (req, res): Promise<void> => {
  privateResponse(res);
  if (!featureEnabled(res)) return;
  if (!await requireMemberIdentity(req, res)) return;
  const id = req.params.videoId;
  const directory = storageDirectory();
  if (!safeId(id) || !directory) {
    res.status(404).json({ error: "Video not found." });
    return;
  }
  const result = await pool.query(
    `SELECT storage_name FROM ${schema}.member_course_videos WHERE id=$1 AND status='published'`,
    [id],
  );
  if (!result.rows[0]) {
    res.status(404).json({ error: "Video not found." });
    return;
  }
  await streamProtectedFile(req, res, path.join(directory, `${id}.mp4`), `${id}.mp4`);
});

export default router;
