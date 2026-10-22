"""Editable content for the Smart Money Hub multiple-choice assessment."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    topic: str
    prompt: str
    options: tuple[str, str, str, str]
    correct_index: int
    explanation: str


QUESTIONS: tuple[Question, ...] = (
    Question(
        topic="Market structure",
        prompt="Which sequence most clearly describes bullish swing structure?",
        options=(
            "Higher highs and higher lows",
            "Lower highs and lower lows",
            "Equal highs and lower lows",
            "A single large bullish candle",
        ),
        correct_index=0,
        explanation=(
            "Bullish structure is usually identified by successive higher highs "
            "and higher lows. A single candle alone does not establish the swing structure."
        ),
    ),
    Question(
        topic="Break of Structure (BOS)",
        prompt=(
            "In an established bullish trend, which event is the clearest bullish BOS?"
        ),
        options=(
            "Price wicks above a swing high but closes below it",
            "A candle closes decisively above a relevant prior swing high",
            "Price touches an order block",
            "Price makes an equal low",
        ),
        correct_index=1,
        explanation=(
            "A decisive close beyond a meaningful swing high supports a bullish "
            "break of structure. A wick by itself can be a liquidity sweep rather "
            "than a confirmed break."
        ),
    ),
    Question(
        topic="Change of Character (CHoCH)",
        prompt=(
            "After a sequence of lower highs and lower lows, price closes above "
            "the latest meaningful lower high. What does this suggest?"
        ),
        options=(
            "A confirmed long entry with no further checks needed",
            "A possible shift in structure that still needs confirmation",
            "A guaranteed continuation of the bearish trend",
            "That risk management is no longer needed",
        ),
        correct_index=1,
        explanation=(
            "A CHoCH can be early evidence that the prior structure is changing. "
            "It is not an entry signal by itself: wait for confirmation and a retest."
        ),
    ),
    Question(
        topic="Liquidity (SSL/BSL)",
        prompt=(
            "Which statement best describes sell-side (SSL) and buy-side (BSL) "
            "liquidity around obvious swing levels?"
        ),
        options=(
            "SSL commonly rests below lows and BSL above highs; a sweep is context, not an entry by itself",
            "SSL is always above highs and BSL always below lows",
            "A liquidity sweep guarantees an immediate reversal",
            "Liquidity only exists inside fair value gaps",
        ),
        correct_index=0,
        explanation=(
            "Sell-side liquidity (SSL) is commonly associated with stops below "
            "lows; buy-side liquidity (BSL) with stops above highs. A sweep can "
            "provide context, but it does not guarantee a reversal or replace confirmation."
        ),
    ),
    Question(
        topic="Order blocks",
        prompt="Which description gives an order block a meaningful reason to watch it?",
        options=(
            "Any candle that is a different color from the next candle",
            "The last opposing candle before displacement that breaks relevant structure",
            "The most recent candle on any chart",
            "A zone chosen only because it is close to current price",
        ),
        correct_index=1,
        explanation=(
            "A commonly used order-block rationale is the last opposing candle "
            "before displacement that breaks structure. Context and confirmation "
            "still matter; not every opposite-colored candle is a valid POI."
        ),
    ),
    Question(
        topic="FVG and IFVG",
        prompt="Which statement best describes an FVG and a possible inverse FVG (IFVG)?",
        options=(
            "An FVG is an imbalance; if price decisively breaks through it, it may act as an IFVG after confirmation",
            "An FVG and an IFVG are both guaranteed reversal zones",
            "An IFVG is simply the middle candle of every three-candle pattern",
            "A gap becomes an IFVG as soon as price touches it",
        ),
        correct_index=0,
        explanation=(
            "An FVG marks a price imbalance. If price breaks through a gap, some "
            "traders watch it as an inverse FVG, but the role change is not an "
            "automatic entry signal; wait for confirmation and respect the broader context."
        ),
    ),
    Question(
        topic="Points of Interest (POIs)",
        prompt="What is the strongest reason to treat a price zone as a POI?",
        options=(
            "It is a round number, regardless of market context",
            "It has a clear structural reason and fits the liquidity and displacement context",
            "Price has touched it many times, so it must hold",
            "It is the nearest visible candle to current price",
        ),
        correct_index=1,
        explanation=(
            "A POI needs a valid reason, such as structural relevance supported by "
            "liquidity and displacement. A label or convenient price level alone "
            "is not enough."
        ),
    ),
    Question(
        topic="Displacement",
        prompt="Which price action is the clearest sign of bullish displacement?",
        options=(
            "Small overlapping candles with no progress",
            "A decisive impulsive move that closes through relevant structure",
            "A single wick that immediately rejects the level",
            "Price moving sideways inside a narrow range",
        ),
        correct_index=1,
        explanation=(
            "Displacement is a forceful move with clear directional progress, "
            "often through relevant structure. It adds confirmation, but does "
            "not remove the need to wait for a retest and manage risk."
        ),
    ),
    Question(
        topic="Retest and confirmation",
        prompt="In a retest-based entry model, what should happen after a breakout before entry?",
        options=(
            "Enter immediately so the move is not missed",
            "Wait for price to retest the relevant level or POI and show a response",
            "Add size while price is moving away from the level",
            "Ignore the level once price has broken it",
        ),
        correct_index=1,
        explanation=(
            "This model waits for price to return to the relevant level or POI and "
            "show a response. If the move leaves first, skip this setup rather than "
            "chase it; other entry models may use different triggers."
        ),
    ),
    Question(
        topic="Confirmation and risk management",
        prompt="Which plan best follows a retest-based Smart Money Hub entry model and sound risk management?",
        options=(
            "Enter as soon as price touches any POI and decide the stop later",
            "After relevant liquidity and displacement, wait for a POI retest and entry confirmation; define risk before entering",
            "Chase a large candle and increase risk if the entry is late",
            "Enter on a CHoCH alone because a stop is optional",
        ),
        correct_index=1,
        explanation=(
            "For this model, a setup uses a valid POI, relevant "
            "liquidity and displacement, then a retest and an entry trigger. Define "
            "the stop and acceptable risk first; skip the trade if the risk is not sound."
        ),
    ),
)


def validate_questions() -> None:
    """Fail at startup/tests if editable question content breaks the quiz contract."""
    if len(QUESTIONS) != 10:
        raise ValueError(f"The assessment must contain exactly 10 questions; found {len(QUESTIONS)}.")

    for number, question in enumerate(QUESTIONS, start=1):
        if len(question.options) != 4:
            raise ValueError(f"Question {number} must contain exactly 4 answer options.")
        if not 0 <= question.correct_index < len(question.options):
            raise ValueError(f"Question {number} has an invalid correct answer index.")
        if not question.topic or not question.prompt or not question.explanation:
            raise ValueError(f"Question {number} is missing required content.")


validate_questions()