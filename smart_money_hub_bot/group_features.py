"""Safe, opt-in learning features for the Smart Money Hub education group."""

from dataclasses import dataclass


DEFAULT_EDUCATION_GROUP_ID = -1003916437804


@dataclass(frozen=True)
class ScenarioPoll:
    question: str
    options: tuple[str, str, str, str]
    correct_option_id: int
    explanation: str


SCENARIO_POLLS: tuple[ScenarioPoll, ...] = (
    ScenarioPoll(
        question=(
            "Hypothetical SMC scenario: During a bearish swing, price wicks above "
            "a prior swing high, then closes back below it. What is the safest read?"
        ),
        options=(
            "A possible liquidity sweep; wait for planned confirmation",
            "A confirmed bullish reversal and automatic long entry",
            "A bearish BOS proven by the wick alone",
            "Proof that institutions deliberately took those stops",
        ),
        correct_option_id=0,
        explanation=(
            "A move beyond a high may be a liquidity sweep, but it does not prove "
            "intent or guarantee a reversal. Wait for your planned confirmation. "
            "NO CONFIRMATION, NO ENTRY."
        ),
    ),
    ScenarioPoll(
        question=(
            "Hypothetical SMC scenario: In bullish structure, a candle closes "
            "decisively above a meaningful prior swing high with displacement. "
            "What may this show?"
        ),
        options=(
            "A possible bullish BOS; it is not an entry by itself",
            "A guaranteed continuation with no risk planning needed",
            "A bearish CHOCH because price moved quickly",
            "A valid entry whenever price touches the level again",
        ),
        correct_option_id=0,
        explanation=(
            "A decisive break of a relevant swing can support a bullish BOS read. "
            "Still apply your entry, invalidation, and risk rules. "
            "NO CONFIRMATION, NO ENTRY."
        ),
    ),
    ScenarioPoll(
        question=(
            "Hypothetical SMC scenario: After lower highs and lower lows, price "
            "closes above the latest meaningful lower high. What is the cautious read?"
        ),
        options=(
            "A possible CHOCH; a reversal is not guaranteed",
            "A confirmed long entry without more checks",
            "A guaranteed continuation of the bearish move",
            "Proof that a specific institution changed direction",
        ),
        correct_option_id=0,
        explanation=(
            "A CHOCH may signal a possible structure shift. Look for the "
            "confirmation required by your plan; it does not guarantee reversal. "
            "NO CONFIRMATION, NO ENTRY."
        ),
    ),
    ScenarioPoll(
        question=(
            "Hypothetical SMC scenario: Price returns to a fair value gap after "
            "an impulsive move. What should a disciplined trader do?"
        ),
        options=(
            "Treat it as a possible POI and wait for planned confirmation",
            "Enter immediately because every gap must hold",
            "Assume price will reverse from the gap",
            "Ignore invalidation because displacement already happened",
        ),
        correct_option_id=0,
        explanation=(
            "An FVG can be an area to study, not an automatic entry signal. "
            "Wait for your setup's confirmation and define risk first. "
            "NO CONFIRMATION, NO ENTRY."
        ),
    ),
)


def scenario_for_message_id(message_id: int) -> ScenarioPoll:
    """Select a stable, rotating scenario based on the Telegram command message."""
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        message_id = 0
    return SCENARIO_POLLS[message_id % len(SCENARIO_POLLS)]
