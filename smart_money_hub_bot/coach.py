"""Provider-neutral DM coaching with a deterministic, offline first version."""

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CoachReply:
    response: str
    detected_topic: str
    mistakes: tuple[str, ...]
    lesson_learned: str


class CoachService(Protocol):
    def evaluate(self, message: str) -> CoachReply: ...


class RuleBasedCoachService:
    """Local SMC coach. It makes no network or paid-AI calls."""

    _topic_aliases: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("CHoCH", ("change of character", "choch")),
        ("BOS", ("break of structure", "bos")),
        ("MSS", ("market structure shift", "mss")),
        ("FVG / IFVG", ("inversion fair value gap", "fair value gap", "ifvg", "fvg")),
        ("Order Blocks", ("order block", "order blocks", "ob")),
        ("Liquidity / SSL / BSL", ("sell-side liquidity", "buy-side liquidity", "ssl", "bsl", "liquidity")),
        ("POI", ("point of interest", "poi")),
        ("Displacement", ("displacement", "impulsive move")),
        ("Retest", ("retest",)),
        ("Confirmation", ("confirmation", "confirm")),
        ("HTF / LTF Analysis", ("higher timeframe", "lower timeframe", "htf", "ltf", "top down")),
        ("Risk Management", ("risk management", "position size", "risk per trade", "stop loss", "stop-loss")),
        ("Partial Profits", ("partial profit", "partials", "take partials")),
        ("Break-Even", ("break even", "break-even", "breakeven")),
        ("Trade Psychology", ("psychology", "emotional", "revenge trade", "fear of missing out", "fomo")),
        ("Trading Discipline", ("discipline", "trading plan", "followed my plan", "followed plan")),
        ("Market Structure", ("market structure", "higher high", "lower low", "swing high", "swing low", "structure")),
    )

    _topic_guides: dict[str, tuple[str, str]] = {
        "CHoCH": (
            "A Change of Character is an early break against the current swing pattern. It can warn that order flow is changing, but it does not guarantee a reversal.",
            "Which swing level broke, and did price show displacement and a retest afterward?",
        ),
        "BOS": (
            "A Break of Structure is a break through a relevant swing in the direction of the current move. Check the close, displacement, and higher-timeframe context rather than treating every wick as a BOS.",
            "Which swing level was broken, and what would invalidate your read?",
        ),
        "MSS": (
            "A Market Structure Shift is evidence that short-term order flow may have changed, often after a liquidity event and a strong displacement. It is context, not a guaranteed entry.",
            "What liquidity was taken before the shift, and did price retest your POI?",
        ),
        "FVG / IFVG": (
            "A Fair Value Gap marks an imbalance from a fast move. It can be a POI, but a gap alone is not confirmation. An IFVG is a gap that has been invalidated and may be treated as an opposing area.",
            "Did price take liquidity and show confirmation before the retest?",
        ),
        "Order Blocks": (
            "An Order Block is a possible reaction area around the last opposing candle before a strong displacement. It is a POI to study, not a promise that price will react there.",
            "What structure or liquidity event supports this block, and what is your invalidation?",
        ),
        "Liquidity / SSL / BSL": (
            "Liquidity often gathers around obvious highs and lows. BSL is buy-side liquidity above highs; SSL is sell-side liquidity below lows. A sweep is context, not an entry signal by itself.",
            "Which side was swept, and what did price do after the sweep?",
        ),
        "POI": (
            "A Point of Interest is an area where you will watch for a setup. It is not an entry trigger by itself; wait for the confirmation and retest your plan requires.",
            "What makes this POI relevant, and what confirmation would you need there?",
        ),
        "Displacement": (
            "Displacement is a decisive, impulsive move away from an area. It can help confirm intent, but it still needs to fit the structure and risk plan.",
            "What level did the displacement break, and where would the move be invalidated?",
        ),
        "Retest": (
            "A retest is price returning to a broken level or POI after the initial move. It gives you a chance to assess the reaction; it does not mean you must enter.",
            "Did the retest hold with confirmation, or did price close back through the level?",
        ),
        "Confirmation": (
            "Confirmation is evidence that your planned setup is developing, such as a meaningful structure shift or displacement at the POI. A zone or indicator alone is not confirmation.",
            "What specific price action would make you enter, and what would make you stand aside?",
        ),
        "HTF / LTF Analysis": (
            "Use the higher timeframe to frame bias and important areas, then the lower timeframe to look for timing and confirmation. If they conflict, reduce certainty rather than forcing a trade.",
            "What is the HTF context, and what LTF event would confirm or invalidate your idea?",
        ),
        "Risk Management": (
            "Risk comes first: decide where the setup is invalidated, size the position to a fixed risk limit, and know the loss before entry. A stop should follow the setup logic, not a hoped-for outcome.",
            "Where is your invalidation, and how much of your account would the stop risk?",
        ),
        "Partial Profits": (
            "Plan partial profits before entry around meaningful levels and your risk plan. Taking partials should reduce risk by design, not be a reaction to fear.",
            "What level in your plan would justify taking a partial?",
        ),
        "Break-Even": (
            "Moving a stop to break-even too early can expose a valid setup to noise. Define the structure or milestone that must occur before you move it.",
            "What planned event would justify moving your stop to break-even?",
        ),
        "Trade Psychology": (
            "Notice the emotion without letting it choose the trade. If fear, frustration, or FOMO is driving the decision, pause and compare the setup with your written rules.",
            "Which emotion is strongest right now, and what does your plan say to do?",
        ),
        "Trading Discipline": (
            "Discipline means following the written process, including skipping trades that lack confirmation. Review decisions by process, not just by whether they won or lost.",
            "Which rule will you check before your next entry?",
        ),
        "Market Structure": (
            "Market structure describes the sequence of meaningful swing highs and lows. Higher highs and higher lows suggest upward structure; lower highs and lower lows suggest downward structure. A range can be unclear.",
            "Which swing points define the current structure on your chosen timeframe?",
        ),
    }

    def evaluate(self, message: str) -> CoachReply:
        text = " ".join(message.split())
        normalized = text.casefold()
        if not text:
            return CoachReply(
                "Tell me what you are studying or what happened in a setup. "
                "I can help you reason through structure, liquidity, confirmation, retests, and risk.",
                "General SMC",
                (),
                "Describe the setup before deciding whether it fits your rules.",
            )

        if self._is_stop_out_message(normalized):
            return CoachReply(
                self._trade_review_questions(),
                "Trade Review",
                (),
                "A stop-out alone does not prove a mistake; review the process and risk plan.",
            )

        topic = self._detect_topic(normalized)
        if self._looks_like_trade_review_answer(normalized):
            mistakes = self._identify_mistakes(normalized)
            return self._review_feedback(topic, mistakes)

        mistakes = self._identify_mistakes(normalized)
        if (
            topic == "FVG / IFVG"
            and self._contains_any(normalized, ("entered immediately", "entered right away", "entered straight away", "bought immediately", "sold immediately"))
        ):
            mistakes = tuple(dict.fromkeys((*mistakes, "Entered at an FVG without clear confirmation")))
            return CoachReply(
                "An FVG can be a POI, but the gap by itself is not an entry confirmation. "
                "If you entered as soon as you saw it, you may have skipped the liquidity "
                "and reaction checks your plan requires. No confirmation, no entry. "
                "No retest, no entry. Did price take SSL/BSL, show displacement, and then retest?",
                topic,
                mistakes,
                "Treat an FVG as an area to watch; wait for planned confirmation and a retest.",
            )

        if topic in self._topic_guides:
            explanation, check_question = self._topic_guides[topic]
            response = f"{explanation}\n\n{check_question}"
            if mistakes:
                response += "\n\nFrom what you wrote, review: " + "; ".join(mistakes) + "."
            response += "\n\nRisk management first. This is education, not a trade signal."
            return CoachReply(
                response,
                topic,
                mistakes,
                explanation,
            )

        if mistakes:
            return self._review_feedback(topic, mistakes)

        return CoachReply(
            "I can help you understand your own setup rather than give you an entry. "
            "What is the HTF context and POI? What liquidity was taken? What confirmation "
            "and retest did you see, and where is the setup invalidated?\n\n"
            "No confirmation, no entry. No retest, no entry. Don't chase missed trades. "
            "Risk management first.",
            topic,
            (),
            "Describe the structure, liquidity, confirmation, retest, and invalidation before acting.",
        )

    @classmethod
    def _detect_topic(cls, text: str) -> str:
        for topic, aliases in cls._topic_aliases:
            if cls._contains_any(text, aliases):
                return topic
        return "General SMC"

    @staticmethod
    def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(phrase.casefold())}(?!\w)", text)
            for phrase in phrases
        )

    @staticmethod
    def _is_stop_out_message(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:got\s+)?stopped\s+out\b|\bstop(?:ped)?\s+loss\s+(?:was\s+)?hit\b|\bsl\s+hit\b",
                text,
            )
        )

    @staticmethod
    def _looks_like_trade_review_answer(text: str) -> bool:
        fields = (
            r"\bpoi\b\s*(?::|=|\bis\b|\bwas\b)",
            r"\btime\s?frame\b\s*(?::|=|\bis\b|\bwas\b)",
            r"\bliquidity\b\s*(?::|=|\bwas\b|\btaken\b)",
            r"\bconfirmation\b\s*(?::|=|\bwas\b|\bis\b)",
            r"\bretest\b\s*(?::|=|\bwas\b|\bwaited\b)",
            r"\b(?:stop\s?loss|sl)\b\s*(?::|=|\bwas\b|\bat\b)",
            r"\bplan\b\s*(?::|=|\bwas\b|\bfollowed\b)",
        )
        return sum(bool(re.search(pattern, text)) for pattern in fields) >= 2

    @staticmethod
    def _identify_mistakes(text: str) -> tuple[str, ...]:
        mistakes: list[str] = []
        if re.search(
            r"\b(?:no|without|missing|lacked)\s+(?:clear\s+)?confirmation\b"
            r"|\bconfirmation\s*(?::|=|was|is)?\s*(?:none|no|missing|absent)\b"
            r"|\bentered\s+before\s+confirmation\b"
            r"|\bentered\s+without\s+confirmation\b",
            text,
        ):
            mistakes.append("Entry was taken without confirmation")
        if re.search(
            r"\bno\s+retest\b|\bwithout\s+(?:a\s+)?retest\b"
            r"|\b(?:didn['’]?t|did\s+not)\s+wait\s+for\s+(?:a\s+)?retest\b"
            r"|\bentered\s+before\s+(?:the\s+)?retest\b"
            r"|\bretest\s*(?::|=|was|is)?\s*(?:no|not|none|missing|absent)\b",
            text,
        ):
            mistakes.append("Entry was taken before a retest")
        if re.search(r"\bchased?\s+(?:the\s+)?(?:missed\s+)?(?:trade|setup|move)\b|\bchasing\s+missed\b", text):
            mistakes.append("Chased a missed trade or setup")
        if re.search(
            r"\b(?:oversized|too much risk|risked too much|no risk limit|"
            r"risk was not defined|risk wasn['’]?t defined)\b",
            text,
        ):
            mistakes.append("Risk was oversized or not defined")
        if re.search(
            r"\b(?:didn['’]?t|did\s+not|failed\s+to)\s+follow\s+(?:my\s+)?plan\b"
            r"|\bignored\s+(?:my\s+)?plan\b"
            r"|\b(?:did\s+you\s+)?follow(?:ed)?\s+(?:my\s+|your\s+)?plan\s*"
            r"(?::|=|was|is)?\s*(?:no|not|false)\b"
            r"|\bplan\s*(?::|=|was|is)\s*(?:no|not followed)\b",
            text,
        ):
            mistakes.append("The written plan was not followed")
        if re.search(
            r"\bmoved\s+(?:my\s+)?(?:sl|stop(?:\s?loss)?)\s+"
            r"(?:to\s+)?(?:break[\s-]?even|be)\s+(?:too\s+early|unnecessarily|without\s+(?:a\s+)?plan)\b",
            text,
        ):
            mistakes.append("The stop was moved without the plan's criteria")
        return tuple(mistakes)

    @staticmethod
    def _trade_review_questions() -> str:
        return (
            "Let's review the process, not just the outcome. Reply with these details "
            "(you can answer them all in one message):\n"
            "1. What was your POI?\n"
            "2. What timeframe?\n"
            "3. What liquidity was taken?\n"
            "4. What confirmation did you see?\n"
            "5. Did price retest?\n"
            "6. Where was your stop loss?\n"
            "7. Did you follow your plan?\n\n"
            "I’ll help identify possible process mistakes. A loss by itself does not mean the setup was wrong."
        )

    @staticmethod
    def _review_feedback(topic: str, mistakes: tuple[str, ...]) -> CoachReply:
        if mistakes:
            response = (
                "Based on what you shared, these are possible process issues to review:\n"
                + "\n".join(f"• {mistake}" for mistake in mistakes)
                + "\n\nCompare each one with your written plan; don't judge the setup from the loss alone. "
                "No confirmation, no entry. No retest, no entry. Don't chase missed trades. "
                "Risk management first.\n\nWhich rule would you change or reinforce next time?"
            )
            lesson = "A repeatable process matters more than the outcome of one trade."
        else:
            response = (
                "I don't see an obvious rule breach in the details you shared. A stop-out "
                "can happen even when a setup follows the plan. Check whether the stop was "
                "beyond your invalidation level and within your risk limit, then record the result."
            )
            lesson = "A stop-out alone does not prove a process mistake; compare execution with the plan."
        return CoachReply(response, topic, mistakes, lesson)


def ai_evaluate_answer(message: str, service: CoachService) -> CoachReply:
    """Provider seam; this version delegates to a local deterministic service."""
    return service.evaluate(message)
