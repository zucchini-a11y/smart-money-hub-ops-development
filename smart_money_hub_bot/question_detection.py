"""Detect member questions that should be tracked for knowledge quality review."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionAssessment:
    question: str
    topic: str
    confidence: str
    review_reason: str

    @property
    def needs_research(self) -> bool:
        return self.confidence == "low"


_QUESTION_START = re.compile(
    r"^(?:what|when|where|who|whom|whose|which|why|how|is|are|am|was|were|"
    r"do|does|did|can|could|would|should|will|may|might|explain|define|"
    r"compare|tell me|help me understand)\b",
    re.IGNORECASE,
)
_NON_QUESTIONS = (
    re.compile(
        r"^(?:hey|hello|hi|hiya|yo|yoo|thanks|thank you|cheers)"
        r"(?:\s+(?:bro|sis|there|coach))?[!. ]*$",
        re.I,
    ),
    re.compile(r"^(?:setup review|mistake review):", re.I),
    re.compile(
        r"^(?:how are you|how'?s it going|what'?s up|who are you|"
        r"what'?s your name|where are you from|are you a bot|"
        r"what can you do|you good|are you okay|how'?s your day|"
        r"what'?s going on)[?!. ]*$",
        re.I,
    ),
)
_SUPPORTED_TOPICS = {
    "CHoCH",
    "BOS",
    "MSS",
    "FVG / IFVG",
    "Order Blocks",
    "Liquidity / SSL / BSL",
    "POI",
    "Displacement",
    "Retest",
    "Confirmation",
    "HTF / LTF Analysis",
    "Risk Management",
    "Risk:Reward",
    "Stop Loss",
    "Take Profit",
    "Partial Profits",
    "Break-Even",
    "FOMO",
    "Revenge Trading",
    "Trade Psychology",
    "Trading Discipline",
    "Market Structure",
}
_TIME_SENSITIVE = re.compile(
    r"\b(?:today|right now|current|currently|latest|live price|news today|"
    r"economic release|broker rule|leverage|spread|swap|withdrawal|"
    r"funding rate|margin requirement|nfp|cpi|fomc|pce)\b",
    re.I,
)
_COMPARISON = re.compile(
    r"\b(?:difference between|compare|versus|vs\.?|distinguish|"
    r"tell .* apart|how .* different)\b",
    re.I,
)


def detect_member_question(
    message: str, detected_topic: str
) -> QuestionAssessment | None:
    """Return a review assessment for a genuine question, never for casual chat."""
    question = " ".join(message.split()).strip()
    if not question or any(pattern.search(question) for pattern in _NON_QUESTIONS):
        return None
    if re.match(r"^what\s+(?:a|an)\b", question, re.I):
        return None

    looks_like_question = (
        question.endswith("?")
        or bool(_QUESTION_START.match(question))
        or bool(re.match(r"^(?:i need help with|tell me about)\b", question, re.I))
    )
    if not looks_like_question:
        return None

    lowered = question.casefold()
    if _TIME_SENSITIVE.search(lowered):
        return QuestionAssessment(
            question,
            _category_for_topic(detected_topic, question),
            "low",
            "This may depend on current prices, broker rules, or time-sensitive information.",
        )
    if detected_topic not in _SUPPORTED_TOPICS:
        return QuestionAssessment(
            question,
            _category_for_topic(detected_topic, question),
            "low",
            "The Coach does not have a vetted answer for this question yet.",
        )
    if _COMPARISON.search(lowered):
        return QuestionAssessment(
            question,
            _category_for_topic(detected_topic, question),
            "low",
            "This comparison needs a dedicated, reviewed explanation.",
        )
    return QuestionAssessment(
        question,
        _category_for_topic(detected_topic, question),
        "high",
        "Answered using the Coach's existing SMC lesson.",
    )


def _category_for_topic(topic: str, message: str) -> str:
    text = message.casefold()
    if any(word in text for word in ("broker", "platform", "leverage", "spread", "swap", "margin")):
        return "Broker and Platform Questions"
    if any(
        word in text
        for word in (
            "news", "inflation", "interest rate", "rate decision", "economic",
            "fundamental", "nfp", "cpi", "fomc", "pce", "payroll", "central bank",
        )
    ):
        return "Economic News and Fundamentals"
    if _TIME_SENSITIVE.search(text):
        return "Current Market Information"
    if topic in {"CHoCH", "BOS", "MSS"}:
        return "BOS, CHOCH and MSS"
    if topic == "Market Structure":
        return "Market Structure"
    if topic == "Liquidity / SSL / BSL":
        return "Liquidity"
    if topic == "Order Blocks":
        return "Order Blocks"
    if topic == "FVG / IFVG":
        return "FVG and IFVG"
    if topic == "POI":
        return "POIs"
    if topic in {"Displacement", "Retest"}:
        return "Displacement and Retests"
    if topic == "Confirmation":
        return "Confirmation"
    if topic in {"Risk Management", "Risk:Reward", "Stop Loss"}:
        return "Risk Management"
    if topic in {"Take Profit", "Partial Profits", "Break-Even"}:
        return "Trade Management"
    if topic in {"FOMO", "Revenge Trading", "Trade Psychology", "Trading Discipline"}:
        return "Trade Psychology"
    return "General"
