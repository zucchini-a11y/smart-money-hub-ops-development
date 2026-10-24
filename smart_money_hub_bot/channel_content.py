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
        if not any(
            phrase.casefold() in text.casefold()
            for phrase in PROMO_FEATURES
        ):
            return "unverified_promo_feature"
    elif _TELEGRAM_LINK.search(text):
        return "unexpected_bot_promotion"
    return None


def next_category(categories: Sequence[str], sequence: int) -> str:
    if not categories:
        raise ValueError("At least one channel content category is required.")
    return categories[sequence % len(categories)]
