import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def _private_forum_message_target(value):
    """Return (chat_id, topic_id) for a Telegram private forum topic or message link."""
    try:
        parsed = urlsplit(value)
        parts = [part for part in parsed.path.split("/") if part]
        if (parsed.scheme != "https" or (parsed.hostname or "").lower() not in ("t.me", "www.t.me")
                or parsed.username or parsed.password or len(parts) not in (3, 4) or parts[0] != "c"
                or not all(part.isdigit() for part in parts[1:])):
            return None
        return int("-100" + parts[1]), int(parts[2])
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Config:
    token: str = field(repr=False)
    admin: int = 0
    signals: int = 0
    analysis: int = 0
    data: Path = Path("data")
    retention: int = 14
    database_url: str = field(default="", repr=False)
    allow_publishing: bool = False
    isolated_test: bool = False
    education_link: str = field(default="", repr=False)
    education_group_id: int = field(default=0, repr=False)
    exness_partner_link: str = field(default="", repr=False)
    database_schema: str = "smh"
    education_video_group_id: int = field(default=0, repr=False)
    education_video_topic_id: int = field(default=0, repr=False)
    education_video_topic_name: str = "Video tutorials"
    education_video_data_dir: Path = Path("data/education-videos")
    applicant_followups_enabled: bool = False
    education_announcement_url: str = field(default="", repr=False)
    education_episode_01_url: str = field(default="", repr=False)
    education_demo_account_url: str = field(default="", repr=False)
    education_onboarding_enabled: bool = False
    education_day2_mode: str = "online"
    education_market_structure_video_url: str = field(default="", repr=False)
    education_coach_bot_url: str = field(default="", repr=False)
    education_episode_02_video_url: str = field(default="", repr=False)
    education_episode_02_pdf_url: str = field(default="", repr=False)

    @classmethod
    def load(cls):
        isolated = os.getenv("SMH_ISOLATED_TEST_INSTANCE", "false").lower() == "true"
        prefix = "SMH_TEST_" if isolated else ""
        token_key = prefix + "TELEGRAM_BOT_TOKEN"
        token = os.getenv(token_key, "")
        if not token or ":" not in token:
            raise ValueError(f"{token_key} is missing or malformed; configure the isolated test bot secret." if isolated
                             else "TELEGRAM_BOT_TOKEN is missing or malformed; configure Secrets.")
        education_key = "SMH_TEST_EDUCATION_LINK" if isolated else "SMH_EDUCATION_LINK"
        education_link = os.getenv(education_key, "").strip()
        partner_key = "SMH_TEST_EXNESS_PARTNER_LINK" if isolated else "EXNESS_PARTNER_LINK"
        partner_link = os.getenv(partner_key, "").strip()
        if partner_link:
            parsed_partner = urlsplit(partner_link)
            host = (parsed_partner.hostname or "").lower()
            if (parsed_partner.scheme != "https" or parsed_partner.username or parsed_partner.password or
                    not (host == "exness.com" or host.endswith(".exness.com") or
                         host == "exnessonelink.com" or host.endswith(".exnessonelink.com"))):
                raise ValueError(f"{partner_key} must be an HTTPS Exness partner URL.")
        def number(key):
            try:
                return int(os.getenv(prefix + key, "0"))
            except ValueError:
                raise ValueError(f"{prefix + key} must be a numeric Telegram ID.") from None
        video_prefix = "SMH_TEST_" if isolated else "SMH_"
        video_topic_name_key = video_prefix + "EDUCATION_VIDEO_TOPIC_NAME"
        video_topic_name = os.getenv(video_topic_name_key, "Video tutorials").strip()
        video_storage_key = video_prefix + "EDUCATION_VIDEO_STORAGE_DIR"
        announcement_key = prefix + "EDUCATION_ANNOUNCEMENT_URL"
        episode_01_key = prefix + "EDUCATION_EPISODE_01_URL"
        demo_account_key = prefix + "EDUCATION_DEMO_ACCOUNT_URL"
        market_structure_video_key = prefix + "EDUCATION_MARKET_STRUCTURE_VIDEO_URL"
        episode_02_video_key = prefix + "EDUCATION_EPISODE_02_VIDEO_URL"
        episode_02_pdf_key = prefix + "EDUCATION_EPISODE_02_PDF_URL"
        coach_bot_key = prefix + "COACH_BOT_URL"
        announcement_url = os.getenv(announcement_key, "").strip()
        episode_01_url = os.getenv(episode_01_key, "").strip()
        demo_account_url = os.getenv(demo_account_key, "").strip()
        market_structure_video_url = os.getenv(market_structure_video_key, "").strip()
        episode_02_video_url = os.getenv(episode_02_video_key, "").strip()
        episode_02_pdf_url = os.getenv(episode_02_pdf_key, "").strip()
        coach_bot_url = os.getenv(coach_bot_key, "").strip()
        onboarding_enabled = os.getenv(prefix + "EDUCATION_ONBOARDING_ENABLED", "false").lower() == "true"
        day2_mode = os.getenv(prefix + "EDUCATION_DAY2_MODE", "online").strip().lower()
        def video_number(name):
            try:
                return int(os.getenv(video_prefix + name, "0"))
            except ValueError:
                raise ValueError(f"{video_prefix + name} must be a numeric Telegram ID.") from None
        video_group_id = video_number("EDUCATION_VIDEO_GROUP_ID")
        video_topic_id = video_number("EDUCATION_VIDEO_TOPIC_ID")
        database_schema = os.getenv("SMH_TEST_DATABASE_SCHEMA", "smh_test") if isolated else "smh"
        data_dir = Path(os.getenv("SMH_TEST_DATA_DIR" if isolated else "SMH_DATA_DIR",
                                  "data-test" if isolated else "data")).resolve()
        video_data_dir = Path(os.getenv(video_storage_key, str(data_dir / "education-videos"))).resolve()
        if isolated and database_schema != "smh_test":
            raise ValueError("Isolated test storage must use the smh_test schema.")
        c = cls(token, number("ADMIN_TELEGRAM_ID"), number("PRO_SIGNALS_CHANNEL_ID"),
                number("MARKET_ANALYSIS_CHANNEL_ID"),
                data_dir,
                int(os.getenv("SMH_BACKUP_RETENTION", "14")),
                os.getenv("SMH_TEST_DATABASE_URL", "") if isolated else
                (os.getenv("SMH_DATABASE_URL") or os.getenv("DATABASE_URL", "")),
                os.getenv("SMH_TEST_ALLOW_PUBLISHING", "false").lower() == "true" if isolated else
                os.getenv("SMH_ALLOW_PUBLISHING", "false").lower() == "true",
                 isolated, education_link, number("EDUCATION_GROUP_ID"), partner_link,
                 database_schema, video_group_id, video_topic_id,
                 video_topic_name or "Video tutorials", video_data_dir,
                  os.getenv(prefix + "APPLICANT_FOLLOWUPS_ENABLED", "false").lower() == "true",
                    announcement_url, episode_01_url, demo_account_url, onboarding_enabled, day2_mode,
                      market_structure_video_url, coach_bot_url, episode_02_video_url,
                      episode_02_pdf_url)
        if c.admin < 0 or c.signals > 0 or c.analysis > 0:
            raise ValueError("Admin ID must be positive; channel IDs must be negative.")
        if c.signals and c.signals == c.analysis:
            raise ValueError("Signals and analysis must use different channels.")
        if c.education_group_id > 0:
            raise ValueError("Education group ID must be a negative Telegram chat ID.")
        if c.education_group_id and c.education_group_id in (c.signals, c.analysis):
            raise ValueError("The education group must be different from both channels.")
        if ((c.education_video_group_id and c.education_video_group_id > -1_000_000_000)
                or c.education_video_topic_id < 0):
            raise ValueError("Education video destination and topic IDs are invalid.")
        if c.education_video_group_id and c.education_video_group_id in (c.signals, c.analysis):
            raise ValueError("The video destination must be separate from PRO Signals and Market Analysis.")
        if bool(c.education_video_group_id) != bool(c.education_video_topic_id):
            raise ValueError("Configure both the Education video group ID and topic ID together.")
        if c.education_day2_mode != "online" and not (
                len(c.education_day2_mode) == 5 and c.education_day2_mode[2] == ":"
                and c.education_day2_mode[:2].isdigit() and c.education_day2_mode[3:].isdigit()
                and int(c.education_day2_mode[:2]) < 24 and int(c.education_day2_mode[3:]) < 60):
            raise ValueError("EDUCATION_DAY2_MODE must be 'online' or a Lagos time in HH:MM format.")
        education_topics = []
        for key, url in ((announcement_key, c.education_announcement_url),
                         (episode_01_key, c.education_episode_01_url),
                         (demo_account_key, c.education_demo_account_url),
                         (episode_02_pdf_key, c.education_episode_02_pdf_url)):
            if not url:
                continue
            target = _private_forum_message_target(url)
            if not target:
                raise ValueError(f"{key} must be an HTTPS Telegram private forum message link.")
            if c.education_group_id and target[0] != c.education_group_id:
                raise ValueError(f"{key} must point to EDUCATION_GROUP_ID.")
            education_topics.append(target[1])
        if c.education_market_structure_video_url:
            target = _private_forum_message_target(c.education_market_structure_video_url)
            if not target:
                raise ValueError(
                    f"{market_structure_video_key} must be an HTTPS Telegram private forum message link."
                )
            video_group = c.education_video_group_id or c.education_group_id
            if video_group and target[0] != video_group:
                raise ValueError(f"{market_structure_video_key} must point to the configured Education video group.")
            if c.education_video_topic_id and target[1] != c.education_video_topic_id:
                raise ValueError(f"{market_structure_video_key} must point to the configured Education video topic.")
        if c.education_episode_02_video_url:
            target = _private_forum_message_target(c.education_episode_02_video_url)
            if not target:
                raise ValueError(
                    f"{episode_02_video_key} must be an HTTPS Telegram private forum message link."
                )
            video_group = c.education_video_group_id or c.education_group_id
            if video_group and target[0] != video_group:
                raise ValueError(f"{episode_02_video_key} must point to the configured Education video group.")
            if c.education_video_topic_id and target[1] != c.education_video_topic_id:
                raise ValueError(f"{episode_02_video_key} must point to the configured Education video topic.")
        if c.education_coach_bot_url:
            parsed_coach = urlsplit(c.education_coach_bot_url)
            coach_path = [part for part in parsed_coach.path.split("/") if part]
            if (parsed_coach.scheme != "https"
                    or (parsed_coach.hostname or "").lower() not in ("t.me", "www.t.me")
                    or parsed_coach.username or parsed_coach.password or len(coach_path) != 1):
                raise ValueError(f"{coach_bot_key} must be an HTTPS t.me bot link.")
        if c.education_onboarding_enabled and not (
                c.education_group_id and c.education_link and
                c.education_announcement_url and c.education_episode_01_url and c.education_coach_bot_url and
                c.education_episode_02_video_url and c.education_episode_02_pdf_url):
            raise ValueError(
                "Education onboarding requires its group, invite, announcement, Episode 01, Episode 02 PDF and video, "
                "and Coach bot links."
            )
        if c.education_video_group_id == c.education_group_id and c.education_group_id:
            if not c.isolated_test:
                raise ValueError("Production must keep the video destination separate from member access.")
            if not c.education_video_topic_id or not education_topics:
                raise ValueError(
                    "A shared Education forum requires configured announcement and Episode 01 links "
                    "so the Video tutorials topic can be kept separate."
                )
            if c.education_video_topic_id in education_topics:
                raise ValueError(
                    "The Video tutorials topic must differ from the Education announcement and lesson topics."
                )
        if not 1 <= c.retention <= 365:
            raise ValueError("Backup retention must be 1–365.")
        # Fail closed on ephemeral hosting rather than imply SQLite is durable.
        if isolated and not c.database_url and os.getenv("SMH_TEST_MODE") != "1":
            raise ValueError("SMH_TEST_DATABASE_URL is required; isolated tests must not reuse production storage.")
        if not c.database_url and os.getenv("SMH_TEST_MODE") != "1":
            raise ValueError("A PostgreSQL connection is required. SQLite is only for isolated tests.")
        return c

    @property
    def ready(self):
        return bool(self.admin and self.signals and self.analysis)

    def authorize(self, user_id, chat_type="private"):
        if not self.admin or user_id != self.admin or chat_type != "private":
            raise PermissionError("This action is not available.")

    def destination(self, kind, destination):
        if not self.ready:
            raise ValueError("Configure admin and both channel IDs before publishing.")
        expected = "analysis" if kind == "analysis" else "signals"
        if destination != expected:
            raise ValueError("This post type is not allowed in that channel.")
        return self.analysis if destination == "analysis" else self.signals
