"""Vetted, source-safe content for scheduled Smart Money Hub channel posts."""

from __future__ import annotations

import re
from collections.abc import Sequence


CHANNEL_CONTENT_CATEGORIES = (
    "education",
    "weekly_market_recap",
    "new_week_preparation",
    "engagement",
    "trading_psychology",
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
    r"pro signals)\b",
    re.IGNORECASE,
)


def compose_routine_post(category: str, sequence: int) -> str:
    posts = ROUTINE_POSTS.get(category)
    if not posts:
        raise ValueError("Unknown channel post category.")
    return posts[sequence % len(posts)]


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
    return (
        f"{routine_text}\n\n{hook}\n{feature}\n\n"
        f"Open @{clean_username} and tap Start: "
        f"https://t.me/{clean_username}\n"
        "The learning Coach is separate from PRO Signals."
    )


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
            "This weekend draft was created before Gemini review was added, so it "
            "is on hold and will not be published automatically. Retry a Gemini "
            "draft or save a validated administrator edit."
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
    if category in {"destination_not_verified", "destination_mismatch"}:
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
