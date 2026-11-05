import test from "node:test";
import assert from "node:assert/strict";
import {
  getEducationVideoDestination,
  decideEducationVideoPublish,
  mayManageEducationVideos,
  validEducationVideoMetadata,
} from "../src/lib/education-video-policy.ts";

test("video tools are owner-only", () => {
  assert.equal(mayManageEducationVideos("owner"), true);
  assert.equal(mayManageEducationVideos("manager"), false);
  assert.equal(mayManageEducationVideos("agent"), false);
  assert.equal(mayManageEducationVideos(undefined), false);
});

test("video destination is separate from member and public destinations", () => {
  const env = {
    SMH_TEST_EDUCATION_VIDEO_GROUP_ID: "-1000000401",
    SMH_TEST_EDUCATION_VIDEO_TOPIC_ID: "8",
    SMH_TEST_EDUCATION_VIDEO_TOPIC_NAME: "Video tutorials",
    SMH_TEST_EDUCATION_GROUP_ID: "-1000000402",
    SMH_TEST_PRO_SIGNALS_CHANNEL_ID: "-1000000403",
    SMH_TEST_MARKET_ANALYSIS_CHANNEL_ID: "-1000000404",
    SMH_TEST_ALLOW_PUBLISHING: "false",
  };
  assert.deepEqual(getEducationVideoDestination(env, "smh_test"), {
    groupId: -1000000401,
    topicId: 8,
    topicName: "Video tutorials",
    publishingEnabled: false,
    available: true,
  });
});

test("production video configuration uses independent video keys and production channel IDs", () => {
  const env = {
    SMH_EDUCATION_VIDEO_GROUP_ID: "-1000000410",
    SMH_EDUCATION_VIDEO_TOPIC_ID: "8",
    EDUCATION_GROUP_ID: "-1000000411",
    PRO_SIGNALS_CHANNEL_ID: "-1000000412",
    MARKET_ANALYSIS_CHANNEL_ID: "-1000000413",
    SMH_ALLOW_PUBLISHING: "false",
  };
  const config = getEducationVideoDestination(env, "smh");
  assert.equal(config.groupId, -1000000410);
  assert.equal(config.available, true);
  assert.equal(config.publishingEnabled, false);
});

test("missing, overlapping, and malformed video destinations fail closed", () => {
  assert.equal(getEducationVideoDestination({}, "smh_test").available, false);
  assert.equal(getEducationVideoDestination({
    SMH_TEST_EDUCATION_VIDEO_GROUP_ID: "-1000000403",
    SMH_TEST_EDUCATION_VIDEO_TOPIC_ID: "8",
    SMH_TEST_PRO_SIGNALS_CHANNEL_ID: "-1000000403",
  }, "smh_test").available, false);
  assert.equal(getEducationVideoDestination({
    SMH_TEST_EDUCATION_VIDEO_GROUP_ID: "not-a-chat",
    SMH_TEST_EDUCATION_VIDEO_TOPIC_ID: "8",
  }, "smh_test").available, false);
});

test("a shared Education forum is allowed only when Video tutorials has its own topic", () => {
  const base = {
    SMH_TEST_EDUCATION_VIDEO_GROUP_ID: "-1003916437804",
    SMH_TEST_EDUCATION_VIDEO_TOPIC_ID: "8",
    SMH_TEST_EDUCATION_GROUP_ID: "-1003916437804",
    SMH_TEST_EDUCATION_ANNOUNCEMENT_URL: "https://t.me/c/3916437804/7/35",
    SMH_TEST_EDUCATION_EPISODE_01_URL: "https://t.me/c/3916437804/6/23",
    SMH_TEST_ALLOW_PUBLISHING: "false",
  };
  assert.equal(getEducationVideoDestination(base, "smh_test").available, true);
  assert.equal(getEducationVideoDestination({
    ...base,
    SMH_TEST_EDUCATION_VIDEO_TOPIC_ID: "6",
  }, "smh_test").available, false);
  assert.equal(getEducationVideoDestination({
    ...base,
    SMH_TEST_EDUCATION_EPISODE_01_URL: "",
  }, "smh_test").available, false);
});

test("production still requires a separate video group", () => {
  const env = {
    SMH_EDUCATION_VIDEO_GROUP_ID: "-1003916437804",
    SMH_EDUCATION_VIDEO_TOPIC_ID: "8",
    EDUCATION_GROUP_ID: "-1003916437804",
    EDUCATION_ANNOUNCEMENT_URL: "https://t.me/c/3916437804/7/35",
    EDUCATION_EPISODE_01_URL: "https://t.me/c/3916437804/6/23",
  };
  assert.equal(getEducationVideoDestination(env, "smh").available, false);
});

test("video uploads require MP4 and remain within the Bot API file-size limit", () => {
  const valid = {
    title: "Market structure",
    caption: "A short lesson",
    fileName: "lesson.mp4",
    byteSize: 10,
    contentType: "video/mp4",
  };
  assert.equal(validEducationVideoMetadata(valid), true);
  assert.equal(validEducationVideoMetadata({ ...valid, byteSize: 50_000_001 }), false);
  assert.equal(validEducationVideoMetadata({ ...valid, fileName: "lesson.mov" }), false);
  assert.equal(validEducationVideoMetadata({ ...valid, contentType: "application/octet-stream" }), false);
});

test("publish duplicate taps reuse the same request and never queue a second time", () => {
  assert.equal(decideEducationVideoPublish("draft", null, "publish-request-123456"), "queue");
  assert.equal(decideEducationVideoPublish("queued", "publish-request-123456", "publish-request-123456"), "accept_existing");
  assert.equal(decideEducationVideoPublish("published", "publish-request-123456", "publish-request-123456"), "accept_existing");
  assert.equal(decideEducationVideoPublish("uncertain", "publish-request-123456", "publish-request-123456"), "accept_existing");
  assert.equal(decideEducationVideoPublish("uncertain", "publish-request-123456", "different-request-1234"), "reject");
  assert.equal(decideEducationVideoPublish("failed", "publish-request-123456", "different-request-1234"), "reject");
});
