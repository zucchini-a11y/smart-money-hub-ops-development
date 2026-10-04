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
        topic="Liquidity",
        prompt="Where is sell-side liquidity commonly found around equal lows?",
        options=(
            "Above the equal lows, where buy stops sit",
            "Below the equal lows, where sell stops may be resting",
            "Only at the midpoint of the range",
            "There is no liquidity near equal lows",
        ),
        correct_index=1,
        explanation=(
            "Sell-side liquidity commonly gathers below obvious lows. A sweep can "
            "provide context, but it does not guarantee that price will reverse."
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
        topic="Fair Value Gaps (FVGs)",
        prompt="In a three-candle bullish FVG, which candles define the imbalance?",
        options=(
            "The first candle's low and the second candle's high",
            "The first candle's high and the third candle's low, with a gap between them",
            "The second candle's open and close",
            "The third candle's high and the first candle's low",
        ),
        correct_index=1,
        explanation=(
            "A bullish three-candle FVG is commonly marked where the third "
            "candle's low is above the first candle's high, leaving an imbalance "
            "between those prices."
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
        topic="Retests",
        prompt="Under the Smart Money Hub rule, what should happen after a breakout before entry?",
        options=(
            "Enter immediately so the move is not missed",
            "Wait for price to retest the relevant level or POI and show a response",
            "Add size while price is moving away from the level",
            "Ignore the level once price has broken it",
        ),
        correct_index=1,
        explanation=(
            "No retest, no entry. Wait for price to return to the relevant level "
            "or POI and look for a response; do not chase a move that has already left."
        ),
    ),
    Question(
        topic="Confirmation and risk management",
        prompt="Which plan best follows Smart Money Hub's entry and risk principles?",
        options=(
            "Enter as soon as price touches any POI and decide the stop later",
            "After relevant liquidity and displacement, wait for a POI retest and entry confirmation; define risk before entering",
            "Chase a large candle and increase risk if the entry is late",
            "Enter on a CHoCH alone because a stop is optional",
        ),
        correct_index=1,
        explanation=(
            "No confirmation, no entry. A setup should have a valid POI, relevant "
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