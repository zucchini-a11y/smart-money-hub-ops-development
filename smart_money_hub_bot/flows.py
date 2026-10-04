"""Editable prompt definitions for journal and check-in conversations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptField:
    key: str
    prompt: str
    kind: str = "text"
    choices: tuple[str, ...] = ()


TRADE_FIELDS: tuple[PromptField, ...] = (
    PromptField("asset", "What pair or asset did you trade?"),
    PromptField("direction", "Was it a buy or a sell?", "choice", ("Buy", "Sell")),
    PromptField("poi", "What was your point of interest (POI)?"),
    PromptField("timeframe", "What timeframe did you use?"),
    PromptField("confirmation", "What confirmation did you see?"),
    PromptField(
        "liquidity_swept",
        "Was relevant liquidity swept?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "waited_for_retest",
        "Did you wait for a retest?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField("stop_loss", "Where was your stop loss?"),
    PromptField("take_profit", "Where was your take profit?"),
    PromptField(
        "partial_profit",
        "Did you take partial profit?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "moved_sl_to_be",
        "Did you move your stop loss to break even?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "result",
        "What was the result?",
        "choice",
        ("Win", "Loss", "Break-even"),
    ),
    PromptField(
        "followed_plan",
        "Did you follow your trading plan?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "mistake",
        "What mistake did you make, if any? Reply “None” if there was no specific mistake.",
    ),
    PromptField("lesson", "What did you learn from this trade?"),
)


WEEKLY_FIELDS: tuple[PromptField, ...] = (
    PromptField("trades_taken", "How many trades did you take this week?", "integer"),
    PromptField("winners", "How many were winners?", "integer"),
    PromptField("losses", "How many were losses?", "integer"),
    PromptField(
        "followed_plan",
        "Did you follow your trading plan?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "entered_without_confirmation",
        "Did you enter any trade without confirmation?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "chased_missed_trade",
        "Did you chase a setup after missing it?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "moved_sl_unnecessarily",
        "Did you move your stop loss unnecessarily?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField(
        "secured_partials",
        "Did you secure partials or break-even according to your plan?",
        "boolean",
        ("Yes", "No"),
    ),
    PromptField("biggest_mistake", "What was your biggest mistake this week?"),
    PromptField("next_focus", "What is your main focus for next week?"),
)


SUNDAY_FIELDS: tuple[PromptField, ...] = (
    PromptField("weekly_goal", "What is your main trading goal for this week?"),
    PromptField("concept_focus", "What SMC concept are you currently working on?"),
    PromptField(
        "mistake_to_avoid",
        "What trading mistake are you determined not to repeat?",
    ),
    PromptField(
        "missed_setup_plan",
        "What will you do if you miss a setup?",
    ),
)
