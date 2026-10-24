"""Vetted, source-safe content for scheduled Smart Money Hub channel posts."""

from __future__ import annotations

from html import escape
import re
from collections.abc import Sequence


CHANNEL_CONTENT_CATEGORIES = (
    "education",
    "weekly_market_recap",
    "new_week_preparation",
    "engagement",
    "trading_psychology",
    "risk_management",
)

ROUTINE_POSTS: dict[str, tuple[str, ...]] = {
    "education": (
        "SMC lesson: A liquidity sweep shows that an obvious high or low was "
        "taken; it does not, by itself, confirm a reversal. Wait for the structure "
        "and confirmation in your plan.\n\nNO CONFIRMATION, NO ENTRY.",
        "SMC lesson: A break of structure (BOS) continues the current structure; "
        "a change of character (CHOCH) can warn of a possible shift. Neither label "
        "guarantees what price will do next.\n\nNO CONFIRMATION, NO ENTRY.",
        "SMC lesson: An order block is an area traders may study for a reaction, "
        "not an automatic entry signal. Define what would confirm or invalidate "
        "your idea before acting.\n\nNO CONFIRMATION, NO ENTRY.",
        "SMC lesson: A fair value gap (FVG) can highlight an imbalance, but price "
        "returning to it is not confirmation by itself. Follow your written setup "
        "rules.\n\nNO CONFIRMATION, NO ENTRY.",
    ),
    "weekly_market_recap": (
        "Weekly review: Look back at your decisions, not only the outcomes. Did "
        "you wait for planned confirmation, respect invalidation, and keep risk "
        "within your rules? Write down one lesson to carry forward.\n\n"
        "NO CONFIRMATION, NO ENTRY.",
        "Weekly review: Pick one trade or missed setup and compare it with your "
        "plan. What evidence was present, what was missing, and what will you do "
        "differently next time?\n\nNO CONFIRMATION, NO ENTRY.",
    ),
    "new_week_preparation": (
        "New-week preparation: Set your higher-timeframe context, mark the areas "
        "you plan to watch, define confirmation and invalidation, and decide your "
        "risk before entry. Standing aside is valid when your conditions are "
        "missing.\n\nNO CONFIRMATION, NO ENTRY.",
        "Before the new week: Write down the setup you are willing to take, the "
        "evidence you need, and the point that proves the idea wrong. If the market "
        "does not meet your conditions, let it go.\n\nNO CONFIRMATION, NO ENTRY.",
    ),
    "engagement": (
        "Quick check-in: Which part of your process needs the most attention this "
        "week—waiting for confirmation, managing risk, or avoiding FOMO? Share one "
        "small action you will take.\n\nNO CONFIRMATION, NO ENTRY.",
        "Trading reflection: What helps you stay patient when price is near a level "
        "you have marked? Share a process habit that works for you.\n\n"
        "NO CONFIRMATION, NO ENTRY.",
        "Community question: Which SMC concept would you like to review next—BOS "
        "and CHOCH, liquidity, order blocks, or FVGs? Tell us what you find "
        "challenging.\n\nNO CONFIRMATION, NO ENTRY.",
    ),
    "trading_psychology": (
        "Trading psychology: Missing a move is not a reason to chase it. Pause, "
        "check whether your planned setup is still present, and accept that some "
        "moves are not yours to take.\n\nNO CONFIRMATION, NO ENTRY.",
        "Trading psychology: After a loss, give yourself space before the next "
        "decision. Review your rules and risk limit instead of trying to win it "
        "back immediately.\n\nNO CONFIRMATION, NO ENTRY.",
        "Trading psychology: A disciplined decision can still lose, and a lucky "
        "outcome does not prove a poor process was sound. Review whether you "
        "followed your plan.\n\nNO CONFIRMATION, NO ENTRY.",
    ),
    "risk_management": (
        "Risk management: Decide what invalidates your idea before entry and size "
        "the position according to your own risk plan.\n\nNO CONFIRMATION, NO ENTRY.",
        "Risk management: A stop belongs where the trade idea is invalidated, not "
        "where discomfort begins. Define it before you enter.\n\n"
        "NO CONFIRMATION, NO ENTRY.",
        "Risk management: Set a loss limit you can follow, then stop when it is "
        "reached. Protecting capital comes before trying to recover a loss.\n\n"
        "NO CONFIRMATION, NO ENTRY.",
    ),
}

PROMO_FEATURES: tuple[str, ...] = (
    "Ask the private Coach for educational explanations of Smart Money Concepts.",
    "Try an SMC assessment or short challenge to check your understanding.",
    "Record trade reviews in a private journal and track your learning progress.",
)

PROMO_HOOKS: tuple[str, ...] = (
    "Want a place to keep learning between classes?",
    "Put this week's lesson into practice at your own pace.",
    "Build a steadier process with a little guided practice.",
)

_BANNED_PROMISES = re.compile(
    r"\b(?:buy\s+now|sell\s+now|guaranteed\s+(?:profit|returns?)|"
    r"risk[- ]free|100\s*%\s*(?:win|success))\b",
    re.IGNORECASE,
)
_UNVERIFIED_MARKET_CLAIMS = re.compile(
    r"\b(?:currently\s+trading\s+at|live\s+price|breaking\s+news|"
    r"latest\s+(?:market|economic)\s+(?:news|data|report)|"
    r"today'?s?\s+(?:gold|xauusd|market)\s+(?:price|move|trend)|"
    r"(?:gold|xauusd)\s+(?:is|was)\s+(?:currently\s+)?(?:at|up|down|rising|falling))\b",
    re.IGNORECASE,
)
_UNVERIFIED_MARKET_NUMBER = re.compile(
    r"\b(?:xauusd|gold|price|cpi|nfp|inflation|rate decision)\b"
    r".{0,60}(?:\$\s?\d|\d+(?:\.\d+)?\s?(?:points?|pips?|%|percent|usd|dollars?))",
    re.IGNORECASE,
)
_TELEGRAM_LINK = re.compile(r"https?://t\.me/\S+", re.IGNORECASE)
_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_PROMO_MARKERS = re.compile(
    r"https?://t\.me/\S+|@[A-Za-z][A-Za-z0-9_]{4,31}|\btap\s+start\b|"
    r"\b(?:bot|assistant|coach|AI)\b|"
    r"\b(?:SMC\s+assessment|private\s+journal|short\s+challenge)\b",
    re.IGNORECASE,
)
_PROMO_FEATURE_TERMS = re.compile(
    r"\b(?:bot|assistant|coach|AI|assessment|quiz|challenge|journal|"
    r"Smart Money Hub)\b",
    re.IGNORECASE,
)
_PROMO_CAPABILITY_VERBS = re.compile(
    r"\b(?:can|will|offers?|provides?|gives?|helps?|teaches?|explains?|"
    r"answers?|checks?|tracks?|records?|analyses|analyzes|predicts?|sends?|"
    r"generates?|guarantees?|has|includes?|features?|supports?|shows?|lets?|"
    r"alerts?|connects?|uses?)\b",
    re.IGNORECASE,
)
_PROMO_BOILERPLATE = re.compile(
    r"\b(?:open\s+@\w+|tap\s+start|the learning coach is separate from "
    r"pro signals|how the bot can help)\b",
    re.IGNORECASE,
)
_WEEKEND_HEADER = re.compile(
    r"^(?:📚|📊|💧|🎯|🛡️|🧠|🤖|🔍|💬)\s+SMART MONEY HUB"
    r"(?:\s+\|\s+[A-Z0-9][A-Z0-9 &/'-]{1,60})?$"
)
_WEEKEND_HEADINGS = {
    "🔍 WHAT TO UNDERSTAND",
    "✅ WHAT TO DO",
    "⚠️ REMEMBER",
    "📌 KEY TAKEAWAYS",
    "🔍 WHAT TO LOOK FOR",
    "📌 CONDITIONS TO WATCH",
    "📚 WHAT THE REVIEW CAN TEACH",
    "💬 YOUR TURN",
    "⚠️ COMMON TRAP",
    "✅ ONE PRACTICAL RESET",
    "✅ WHAT TO DO",
    "🛡️ RISK REMINDER",
    "⚠️ THE GOLDEN RULE",
    "🤖 HOW THE BOT CAN HELP",
}
_WEEKEND_SECTION_HEADING = re.compile(
    r"^(?:🔍|✅|❌|📌|🛡️|⚠️|💬|🤖|📊|📚|🎯|🧠|💧)\s+"
    r"[A-Z0-9][A-Z0-9’' &:-]{2,90}$"
)
_CATEGORY_EMOJI = {
    "education": "📚",
    "weekly_market_recap": "🔍",
    "new_week_preparation": "📊",
    "engagement": "💬",
    "trading_psychology": "🧠",
    "risk_management": "🛡️",
}
_CATEGORY_HEADLINES = {
    "education": (
        "🎯 TODAY’S TRADING LESSON",
        "🎯 STRUCTURE BEFORE ENTRY",
        "🎯 A ZONE IS NOT A SIGNAL",
        "🎯 READ THE IMBALANCE IN CONTEXT",
    ),
    "weekly_market_recap": (
        "🔍 REVIEW THE PROCESS, NOT JUST THE RESULT",
        "🔍 WHAT DID YOUR PLAN TEACH YOU?",
    ),
    "new_week_preparation": (
        "📊 PREPARE BEFORE THE SESSION",
        "📊 DEFINE YOUR CONDITIONS FIRST",
    ),
    "engagement": (
        "💬 COMMUNITY CHECK-IN",
        "💬 YOUR PROCESS QUESTION",
        "💬 THIS WEEK’S PRACTICE",
    ),
    "trading_psychology": (
        "🧠 DON’T CHASE THE MOVE",
        "🧠 PAUSE BEFORE THE NEXT DECISION",
        "🧠 REVIEW THE PROCESS",
    ),
    "risk_management": (
        "🛡️ DEFINE RISK BEFORE ENTRY",
        "🛡️ KNOW WHAT INVALIDATES THE IDEA",
        "🛡️ PROTECT CAPITAL FIRST",
    ),
}
_CATEGORY_SECTION = {
    "education": "🔍 WHAT TO LOOK FOR",
    "weekly_market_recap": "📚 WHAT THE REVIEW CAN TEACH",
    "new_week_preparation": "📌 CONDITIONS TO WATCH",
    "engagement": "💬 YOUR TURN",
    "trading_psychology": "⚠️ COMMON TRAP",
    "risk_management": "✅ WHAT TO DO",
}
_CATEGORY_ACTION = {
    "education": (
        "📌 KEY TAKEAWAY",
        "Treat the zone or label as context, not as an entry signal by itself.",
    ),
    "weekly_market_recap": (
        "✅ NEXT STEP",
        "Write down one process lesson to carry into the next week.",
    ),
    "new_week_preparation": (
        "📌 BEFORE THE SESSION",
        "Use verified levels only, and define invalidation before entry.",
    ),
    "engagement": (
        "✅ SHARE A TAKEAWAY",
        "Keep the discussion focused on learning and process.",
    ),
    "trading_psychology": (
        "✅ ONE PRACTICAL RESET",
        "Pause, review your rules, and decide only when calm.",
    ),
    "risk_management": (
        "📌 BEFORE ENTRY",
        "Write the risk and invalidation into your plan first.",
    ),
}
_INLINE_BOLD_TERMS = re.compile(
    r"\b(?:BOS|CHOCH|MSS|FVG|IFVG|POI|FOMO|liquidity|liquidity sweep|"
    r"order block|fair value gap|"
    r"risk management|stop loss|take profit|confirmation|invalidation|retest)\b|R:R",
    re.IGNORECASE,
)
_SOURCE_LABEL = re.compile(
    r"^(?:SMC lesson|Weekly review|New-week preparation|Before the new week|"
    r"Quick check-in|Trading reflection|Community question|Trading psychology|"
    r"Risk management):\s*",
    re.IGNORECASE,
)
_BRAND_FOOTER = (
    "⚠️ THE GOLDEN RULE\n"
    "NO CONFIRMATION, NO ENTRY.\n\n"
    "— VAYDA | Smart Money Hub"
)


def compose_routine_post(category: str, sequence: int) -> str:
    posts = ROUTINE_POSTS.get(category)
    layout = _CATEGORY_HEADLINES.get(category)
    if not posts or not layout:
        raise ValueError("Unknown channel post category.")
    body = posts[sequence % len(posts)].strip()
    body = re.sub(
        r"\s*NO CONFIRMATION,\s*NO ENTRY\.?\s*$",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip()
    body = _SOURCE_LABEL.sub("", body).strip()
    if not body:
        raise ValueError("Channel post content cannot be empty.")

    emoji = _CATEGORY_EMOJI[category]
    headline = layout[sequence % len(layout)]
    section = _CATEGORY_SECTION[category]
    action_heading, action = _CATEGORY_ACTION[category]
    lines = [
        f"{emoji} SMART MONEY HUB",
        "━━━━━━━━━━━━━━",
        "",
        headline,
        "",
        section,
        body,
        "",
        action_heading,
        action,
    ]
    if category != "engagement":
        lines.extend(
            [
                "",
                "🛡️ RISK REMINDER",
                "Protect your capital. Follow your trading plan.",
            ]
        )
    lines.extend(["", _BRAND_FOOTER])
    return "\n".join(lines)


def compose_promo_post(
    routine_text: str,
    username: str,
    feature_index: int,
    *,
    hook_index: int = 0,
) -> str:
    clean_username = username.removeprefix("@")
    if not _USERNAME.fullmatch(clean_username):
        raise ValueError("Telegram returned an invalid bot username.")
    feature = PROMO_FEATURES[feature_index % len(PROMO_FEATURES)]
    hook = PROMO_HOOKS[hook_index % len(PROMO_HOOKS)]
    body, separator, _footer = routine_text.rpartition(_BRAND_FOOTER)
    if not separator:
        raise ValueError("Routine post is missing its approved brand footer.")
    promotion = (
        "🤖 HOW THE BOT CAN HELP\n\n"
        f"{hook}\n\n{feature}\n\n"
        f"Open @{clean_username} and tap Start: "
        f"https://t.me/{clean_username}\n"
        "The learning Coach is separate from PRO Signals."
    )
    return f"{body.rstrip()}\n\n{promotion}\n\n{_BRAND_FOOTER}"


def is_promotional_content(content: str) -> bool:
    """Detect bot promotion so an edited educational post can drop promo rules."""
    return bool(_PROMO_MARKERS.search(content))


def _unverified_promo_feature_claims(content: str) -> list[str]:
    approved = {feature.casefold().rstrip(".") for feature in PROMO_FEATURES}
    candidates: list[str] = []
    for raw_sentence in re.split(r"(?<=[.!?])\s+|\n+", content.strip()):
        sentence = raw_sentence.strip()
        normalized = sentence.casefold().rstrip(".")
        if not sentence or normalized in approved or _PROMO_BOILERPLATE.search(sentence):
            continue
        if (
            _PROMO_FEATURE_TERMS.search(sentence)
            and _PROMO_CAPABILITY_VERBS.search(sentence)
        ):
            candidates.append(sentence)
    return candidates


def describe_channel_post_rejection(
    content: str,
    category: str,
    *,
    bot_username: str | None = None,
) -> str:
    """Explain a validation failure in plain language without logging content."""
    if category.startswith("gemini_content_rejected_"):
        reason = category.removeprefix("gemini_content_rejected_")
        return (
            "Gemini returned a draft, but it was not published because it failed "
            "this check. The draft is saved for review. "
            + describe_channel_post_rejection(
                content,
                reason,
                bot_username=bot_username,
            )
        )
    if category == "unverified_promo_feature":
        claims = _unverified_promo_feature_claims(content)
        claim_note = (
            "The claim I could not verify is: "
            f"“{claims[0][:280]}”. "
            if claims
            else "I could not match the feature statement to an approved bot feature. "
        )
        approved = "\n".join(f"• {feature}" for feature in PROMO_FEATURES)
        return (
            f"{claim_note}Replace it with one of these verified feature statements:\n"
            f"{approved}\n\n"
            "Or remove the bot promotion completely (feature claim, bot username, "
            "Telegram link, and “tap Start”) to save this as an education post. "
            "Your saved draft is unchanged. Send the complete corrected post, or "
            "/cancel."
        )
    if category == "missing_golden_rule":
        return (
            "The post is missing the required trading rule “NO CONFIRMATION, NO "
            "ENTRY.” Add that exact sentence and resend the complete post. Your "
            "saved draft is unchanged, so you can try again or send /cancel."
        )
    if category == "content_too_long":
        return (
            "The post is longer than Telegram allows. Shorten it to 4,000 "
            "characters or fewer; the saved draft is unchanged."
        )
    if category == "promo_link_mismatch":
        expected = f"https://t.me/{bot_username.removeprefix('@')}" if bot_username else None
        expected_text = f" Use this verified link: {expected}." if expected else ""
        return (
            "The Telegram link does not match the verified Smart Money Hub bot."
            f"{expected_text} Correct it and resend the complete post; your saved "
            "draft is unchanged."
        )
    if category == "promo_username_missing":
        expected = f"@{bot_username.removeprefix('@')}" if bot_username else "the verified bot username"
        return (
            f"The promotional post must include {expected}. Add it and resend the "
            "complete post; your saved draft is unchanged."
        )
    if category == "promo_call_to_action_missing":
        return (
            "The promotional post needs the words “tap Start” so members know what "
            "to do. Add them and resend the complete post; your saved draft is "
            "unchanged."
        )
    if category == "bot_username_unverified":
        return (
            "I could not verify the bot username for this promotion. Remove the "
            "promotion or wait until the verified username is available."
        )
    if category == "prohibited_signal_or_promise":
        match = _BANNED_PROMISES.search(content)
        phrase = f" The phrase is “{match.group(0)}”." if match else ""
        return (
            "This post contains a trading signal or an unsupported promise that "
            "cannot be published here."
            f"{phrase} Remove that wording and resend the complete post; your saved "
            "draft is unchanged."
        )
    if category == "unverified_market_claim":
        return (
            "This post includes a live-market or economic claim that has not been "
            "verified. Replace it with evergreen education or provide verified "
            "source information before saving."
        )
    if category == "unexpected_bot_promotion":
        return (
            "This post mentions a Telegram bot but is not marked as a promotion. "
            "Remove the bot mention, or keep the verified username, link, “tap "
            "Start,” and one approved feature statement."
        )
    if category == "gemini_legacy_draft_held":
        return (
            "This is an older weekend draft that was not generated by Gemini or "
            "approved through an administrator edit. It was held before any send; "
            "this does not mean Gemini rejected a response. Choose Retry AI Draft "
            "to replace it, or edit it and save a validated replacement."
        )
    if category == "weekend_brand_header_missing":
        return (
            "The post must start with a relevant emoji and “SMART MONEY HUB,” "
            "followed by the branded divider and a category heading. Add those "
            "lines and resend the complete draft."
        )
    if category == "weekend_headline_missing":
        return (
            "The post needs a short uppercase headline on the line below its brand "
            "header. Add one and resend the complete draft."
        )
    if category == "weekend_headline_not_uppercase":
        return (
            "The weekend headline must be short and uppercase. Correct that line "
            "and resend the complete draft."
        )
    if category == "markdown_not_supported":
        return (
            "The post contains Markdown markers, but Telegram receives it as HTML. "
            "Remove the Markdown marks; the bot will add safe bold formatting."
        )
    if category == "duplicate_content":
        return (
            "This draft is too similar to a recent channel post. Gemini can retry "
            "with a different topic, or you can edit the saved draft."
        )
    if category == "gemini_rate_limit":
        return (
            "Gemini reached a usage or rate limit, so no weekend post was sent. "
            "Retry the draft later or edit it yourself."
        )
    if category == "telegram_permission_error":
        return (
            "Telegram did not allow the bot to post in the configured Market "
            "Analysis channel. Check that the bot still has permission to post."
        )
    if category in {
        "destination_not_verified",
        "destination_mismatch",
        "destination_verification_unavailable",
    }:
        return (
            "The configured destination could not be verified as the Market "
            "Analysis channel. Nothing was sent; check the channel configuration."
        )
    if category == "posting_permission_missing":
        return (
            "The bot is not confirmed as an administrator with permission to post "
            "in the Market Analysis channel. No post was sent."
        )
    if category == "telegram_rate_limit":
        return (
            "Telegram temporarily limited channel posting. The post was not "
            "confirmed; review it before trying again."
        )
    if category.startswith("gemini_"):
        return (
            "Gemini could not provide a publishable weekend draft. Nothing was sent "
            "to the channel. You can review the saved draft and retry later."
        )
    return (
        "This post did not pass a publishing check. Review the draft, correct the "
        "issue, and try again. Nothing was published."
    )


def validate_weekend_post_format(content: str) -> str | None:
    """Require a compact, branded layout while accepting older branded drafts."""
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    if not lines or not _WEEKEND_HEADER.fullmatch(lines[0]):
        return "weekend_brand_header_missing"
    title_index = 1
    if len(lines) > 1 and _is_brand_divider(lines[1]):
        title_index = 2
    if len(lines) <= title_index:
        return "weekend_headline_missing"
    headline = lines[title_index]
    if not any(character.isalpha() for character in headline):
        return "weekend_headline_missing"
    if len(headline) > 90 or headline != headline.upper():
        return "weekend_headline_not_uppercase"
    if re.search(r"\*\*|__|`", content):
        return "markdown_not_supported"
    return None


def _is_brand_divider(line: str) -> bool:
    return len(line) >= 10 and bool(re.fullmatch(r"[━─—_-]+", line))


def render_weekend_post_html(content: str) -> str:
    """Render a branded post as Telegram HTML after escaping all plain text."""
    if len(content.strip()) > 4000:
        raise ValueError("content_too_long")
    rejection = validate_weekend_post_format(content)
    if rejection:
        raise ValueError(rejection)

    lines = content.strip().splitlines()
    nonempty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    header_index = nonempty_indexes[0]
    first_title_index = nonempty_indexes[1]
    title_index = (
        nonempty_indexes[2]
        if _is_brand_divider(lines[first_title_index].strip())
        else first_title_index
    )

    def render_line(index: int, raw_line: str) -> str:
        line = raw_line.strip()
        if line.startswith(("- ", "* ")):
            line = f"• {line[2:].strip()}"
        if (
            index in {header_index, title_index}
            or line.upper() in _WEEKEND_HEADINGS
            or _WEEKEND_SECTION_HEADING.fullmatch(line)
            or line.casefold().rstrip(".") == "no confirmation, no entry"
        ):
            return f"<b>{escape(line, quote=False)}</b>"
        parts: list[str] = []
        cursor = 0
        for match in _INLINE_BOLD_TERMS.finditer(line):
            parts.append(escape(line[cursor : match.start()], quote=False))
            parts.append(f"<b>{escape(match.group(0), quote=False)}</b>")
            cursor = match.end()
        parts.append(escape(line[cursor:], quote=False))
        return "".join(parts)

    return "\n".join(
        render_line(index, line) if line.strip() else ""
        for index, line in enumerate(lines)
    )


def validate_channel_post(
    content: str,
    *,
    is_promo: bool,
    bot_username: str | None = None,
    verified_market_information: bool = False,
) -> str | None:
    """Return a safe rejection category, or None when content is publishable."""
    text = content.strip()
    if not text:
        return "empty_content"
    if len(text) > 4000:
        return "content_too_long"
    if "no confirmation, no entry" not in text.casefold():
        return "missing_golden_rule"
    if _BANNED_PROMISES.search(text):
        return "prohibited_signal_or_promise"
    if not verified_market_information and (
        _UNVERIFIED_MARKET_CLAIMS.search(text)
        or _UNVERIFIED_MARKET_NUMBER.search(text)
    ):
        return "unverified_market_claim"
    if is_promo:
        if not bot_username:
            return "bot_username_unverified"
        clean_username = bot_username.removeprefix("@")
        if not _USERNAME.fullmatch(clean_username):
            return "bot_username_unverified"
        if f"https://t.me/{clean_username}".casefold() not in text.casefold():
            return "promo_link_mismatch"
        if f"@{clean_username}".casefold() not in text.casefold():
            return "promo_username_missing"
        if "tap start" not in text.casefold():
            return "promo_call_to_action_missing"
        approved_features = any(
            phrase.casefold() in text.casefold() for phrase in PROMO_FEATURES
        )
        unverified_claims = _unverified_promo_feature_claims(text)
        if not approved_features or unverified_claims:
            return "unverified_promo_feature"
    elif _TELEGRAM_LINK.search(text):
        return "unexpected_bot_promotion"
    return None


def next_category(categories: Sequence[str], sequence: int) -> str:
    if not categories:
        raise ValueError("At least one channel content category is required.")
    return categories[sequence % len(categories)]
