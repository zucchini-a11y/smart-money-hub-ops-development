import type { PortalRole } from "./portal-case-policy";

export const MAX_EDUCATION_VIDEO_BYTES = 50_000_000;
export const EDUCATION_VIDEO_CONTENT_TYPE = "video/mp4";

export interface EducationVideoDestination {
  groupId: number;
  topicId: number;
  topicName: string;
  publishingEnabled: boolean;
  available: boolean;
}

function readId(value: string | undefined): number {
  if (!value || !/^-?\d+$/.test(value.trim())) return 0;
  const parsed = Number(value.trim());
  return Number.isSafeInteger(parsed) ? parsed : 0;
}

function privateForumTopic(value: string | undefined): { groupId: number; topicId: number } | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    const parts = url.pathname.split("/").filter(Boolean);
    if (url.protocol !== "https:"
        || !["t.me", "www.t.me"].includes(url.hostname.toLowerCase())
        || parts.length !== 4
        || parts[0] !== "c"
        || !parts.slice(1).every((part) => /^\d+$/.test(part))) {
      return null;
    }
    const groupId = Number(`-100${parts[1]}`);
    const topicId = Number(parts[2]);
    return Number.isSafeInteger(groupId) && Number.isSafeInteger(topicId) && topicId > 0
      ? { groupId, topicId }
      : null;
  } catch {
    return null;
  }
}

export function mayManageEducationVideos(role: PortalRole | undefined): boolean {
  return role === "owner";
}

export function getEducationVideoDestination(
  env: Record<string, string | undefined>,
  supportSchema: string,
): EducationVideoDestination {
  const test = supportSchema === "smh_test";
  const videoPrefix = test ? "SMH_TEST_" : "SMH_";
  const channelPrefix = test ? "SMH_TEST_" : "";
  const groupId = readId(env[`${videoPrefix}EDUCATION_VIDEO_GROUP_ID`]);
  const topicId = readId(env[`${videoPrefix}EDUCATION_VIDEO_TOPIC_ID`]);
  const topicName = (env[`${videoPrefix}EDUCATION_VIDEO_TOPIC_NAME`] ?? "Video tutorials").trim();
  const signals = readId(env[`${channelPrefix}PRO_SIGNALS_CHANNEL_ID`]);
  const analysis = readId(env[`${channelPrefix}MARKET_ANALYSIS_CHANNEL_ID`]);
  const education = readId(env[`${channelPrefix}EDUCATION_GROUP_ID`]);
  const protectedTopics = [
    privateForumTopic(env[`${channelPrefix}EDUCATION_ANNOUNCEMENT_URL`]),
    privateForumTopic(env[`${channelPrefix}EDUCATION_EPISODE_01_URL`]),
  ];
  const publishingEnabled = env[`${videoPrefix}ALLOW_PUBLISHING`] === "true";
  const sharesEducationForum = groupId !== 0 && groupId === education;
  const topicSeparated = !sharesEducationForum
    || (test
      && protectedTopics.every((topic) => topic?.groupId === education)
      && !protectedTopics.some((topic) => topic?.topicId === topicId));
  const available = groupId <= -1_000_000_000
    && topicId > 0
    && Boolean(topicName)
    && ![signals, analysis].includes(groupId)
    && topicSeparated;
  return {
    groupId,
    topicId,
    topicName: topicName || "Video tutorials",
    publishingEnabled,
    available,
  };
}

export function validEducationVideoMetadata(input: {
  title: string;
  caption: string;
  fileName: string;
  byteSize: number;
  contentType: string;
}): boolean {
  return input.title.trim().length >= 2
    && input.title.trim().length <= 120
    && input.caption.trim().length >= 1
    && input.caption.trim().length <= 900
    && input.fileName.length >= 1
    && input.fileName.length <= 160
    && input.fileName.toLowerCase().endsWith(".mp4")
    && Number.isSafeInteger(input.byteSize)
    && input.byteSize > 0
    && input.byteSize <= MAX_EDUCATION_VIDEO_BYTES
    && input.contentType === EDUCATION_VIDEO_CONTENT_TYPE;
}

export type EducationVideoPublishDecision = "accept_existing" | "queue" | "reject";

export function decideEducationVideoPublish(
  status: string,
  existingRequestId: string | null | undefined,
  requestId: string,
): EducationVideoPublishDecision {
  if (existingRequestId === requestId
      && ["queued", "sending", "published", "uncertain"].includes(status)) {
    return "accept_existing";
  }
  return status === "draft" ? "queue" : "reject";
}
