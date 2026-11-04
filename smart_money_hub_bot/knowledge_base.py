"""Lexical retrieval and duplicate grouping for approved offline knowledge."""

import re
from datetime import date
from typing import Any

_WORD = re.compile(r"[a-z0-9]+", re.I)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "between", "can", "do", "does",
    "for", "from", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or",
    "the", "this", "to", "what", "when", "where", "which", "who", "why", "with",
}
_CONCEPT_ALIASES = (
    (("change of character", "choch"), "choch"),
    (("break of structure", "broken structure", "structure break", "bos"), "bos"),
    (("lower high", "lower highs", "lh"), "lowerhigh"),
    (("lower low", "lower lows", "ll"), "lowerlow"),
    (("higher high", "higher highs", "hh"), "higherhigh"),
    (("market structure shift", "mss"), "mss"),
    (("fair value gap", "fvg"), "fvg"),
    (("inversion fair value gap", "ifvg"), "ifvg"),
    (("buy side liquidity", "buy-side liquidity", "bsl"), "bsl"),
    (("sell side liquidity", "sell-side liquidity", "ssl"), "ssl"),
    (("order block", "order blocks", "ob"), "orderblock"),
    (("point of interest", "points of interest", "poi", "pois"), "poi"),
    (("higher timeframe", "higher time frame", "htf"), "htf"),
    (("lower timeframe", "lower time frame", "ltf"), "ltf"),
    (("risk/reward ratio", "risk reward ratio", "risk/reward", "risk reward", "risk to reward", "r:r"), "riskreward"),
    (("stop loss", "stop-loss", "sl"), "stoploss"),
    (("take profit", "take-profit", "tp"), "takeprofit"),
    (("fear of missing out", "fomo"), "fomo"),
    (("revenge trading", "revenge trade"), "revengetrading"),
)


def question_tokens(question: str) -> set[str]:
    normalized = " ".join(question.casefold().split())
    tokens = {word for word in _WORD.findall(normalized) if word not in _STOP_WORDS}
    for aliases, canonical in _CONCEPT_ALIASES:
        if any(
            re.search(
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                normalized,
            )
            for alias in aliases
        ):
            tokens.add(canonical)
    return tokens


def question_similarity(left: str, right: str) -> float:
    left_tokens = question_tokens(left)
    right_tokens = question_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _item_examples(item: dict[str, Any]) -> list[str]:
    examples = item.get("examples") or item.get("question_examples") or []
    if isinstance(examples, str):
        return [examples]
    if isinstance(examples, list):
        return [
            str(example.get("question", "") if isinstance(example, dict) else example)
            for example in examples
        ]
    return []


def find_similar_item(
    question: str,
    topic: str,
    items: list[dict[str, Any]],
    *,
    threshold: float = 0.42,
) -> dict[str, Any] | None:
    """Find a likely duplicate using question wording plus the category."""
    best_item: dict[str, Any] | None = None
    best_score = 0.0
    for item in items:
        examples = _item_examples(item)
        candidates = examples or [str(item.get("topic") or "")]
        lexical_score = max(question_similarity(question, candidate) for candidate in candidates)
        same_topic = str(item.get("topic") or "").casefold() == topic.casefold()
        score = lexical_score + (0.12 if same_topic else 0.0)
        if score > best_score:
            best_item = item
            best_score = score
    return best_item if best_item is not None and best_score >= threshold else None


def find_approved_answer(
    question: str,
    topic: str,
    items: list[dict[str, Any]],
    *,
    threshold: float = 0.54,
) -> dict[str, Any] | None:
    """Return an active approved answer only when wording is a reasonable match."""
    eligible = [
        item
        for item in items
        if item.get("approved_answer")
        and item.get("status") != "retired"
        and not (
            item.get("review_after")
            and str(item["review_after"]) < date.today().isoformat()
        )
    ]
    best_item: dict[str, Any] | None = None
    best_score = 0.0
    best_threshold = threshold
    for item in eligible:
        examples = _item_examples(item)
        candidates = examples or [str(item.get("topic") or "")]
        lexical_score = max(
            (question_similarity(question, example) for example in candidates),
            default=0.0,
        )
        same_topic = str(item.get("topic") or "").casefold() == topic.casefold()
        score = lexical_score + (0.16 if same_topic else 0.0)
        if score > best_score:
            best_item = item
            best_score = score
            best_threshold = threshold if examples else 0.36
    return best_item if best_item is not None and best_score >= best_threshold else None
