"""Provider-neutral DM coaching with a deterministic, offline first version."""

import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class CoachReply:
    response: str
    detected_topic: str
    mistakes: tuple[str, ...]
    lesson_learned: str
    requires_review: bool = False


class CoachProviderError(RuntimeError):
    """A provider call failed without exposing request content or credentials."""

    def __init__(
        self,
        failure_kind: str,
        status_code: int | None = None,
        *,
        elapsed_ms: int | None = None,
        provider_code: int | None = None,
        provider_status: str | None = None,
        provider_message: str | None = None,
        response_headers: dict[str, str] | None = None,
        rejection_category: str | None = None,
    ) -> None:
        self.failure_kind = failure_kind
        self.status_code = status_code
        self.elapsed_ms = elapsed_ms
        self.provider_code = provider_code
        self.provider_status = provider_status
        self.provider_message = provider_message
        self.response_headers = dict(response_headers or {})
        self.rejection_category = rejection_category
        super().__init__(failure_kind)


class CoachService(Protocol):
    def evaluate(
        self,
        message: str,
        *,
        history: list[dict[str, Any]] | None = None,
        profile: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> CoachReply: ...


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
        ("Risk:Reward", ("risk/reward ratio", "risk/reward", "risk reward", "risk to reward", "r:r")),
        ("Stop Loss", ("stop loss", "stop-loss", "sl")),
        ("Take Profit", ("take profit", "take-profit", "tp")),
        ("Risk Management", ("risk management", "position size", "risk per trade")),
        ("Partial Profits", ("partial profit", "partials", "take partials")),
        ("Break-Even", ("break even", "break-even", "breakeven")),
        ("FOMO", ("fear of missing out", "fomo")),
        ("Revenge Trading", ("revenge trading", "revenge trade")),
        ("Trade Psychology", ("psychology", "emotional")),
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
        "Risk:Reward": (
            "Risk-to-reward compares the amount you could lose with the planned target. A 1:2 setup risks one unit to target two; it does not make a trade certain or replace a sound setup.",
            "What is the planned risk and target distance in your setup?",
        ),
        "Stop Loss": (
            "A stop loss marks where your setup is invalidated. Place it from the trade idea and size the position to your fixed risk; don’t widen it just to avoid taking a planned loss.",
            "What price level would invalidate your setup?",
        ),
        "Take Profit": (
            "A take-profit level should come from your plan and relevant price levels. Decide it before entry, and avoid moving it only because of fear or excitement.",
            "Which planned level would make you take profit?",
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
        "FOMO": (
            "FOMO can push you to chase a move that no longer matches your plan. Pause, check whether the setup is still valid, and be willing to let it go.",
            "What confirmation would your plan require before you act?",
        ),
        "Revenge Trading": (
            "Revenge trading is taking another trade mainly to win back a loss. Step away, review your risk limit, and return only when a planned setup appears.",
            "Would you take this setup if the previous trade had been a win?",
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

    def evaluate(
        self,
        message: str,
        *,
        history: list[dict[str, Any]] | None = None,
        profile: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> CoachReply:
        text = " ".join(message.split())
        normalized = text.casefold()
        history = history or []
        profile = profile or {}
        if not text:
            return CoachReply(
                "I’m here. What would you like to work through?",
                "General SMC",
                (),
                "Start with the question or decision you want to understand.",
            )

        if normalized.startswith(("setup review:", "mistake review:")):
            topic = self._detect_topic(normalized)
            mistakes = self._identify_mistakes(normalized)
            trade_was_taken = bool(
                re.search(
                    r"\b(?:i\s+)?(?:entered|took the trade|placed the trade|was in the trade)\b",
                    normalized,
                )
            )
            if mistakes and (
                normalized.startswith("mistake review:") or trade_was_taken
            ):
                return self._review_feedback(topic, mistakes)
            if normalized.startswith("setup review:"):
                return CoachReply(
                    "Thanks, that gives us a useful checklist. You’ve described your "
                    "context, area, and risk plan; I can’t verify a live chart or confirm "
                    "an entry from text alone. What specific event would make you stand aside?",
                    topic,
                    (),
                    "Use the planned invalidation and confirmation rather than forcing a trade.",
                )
            return CoachReply(
                "Thanks for laying it out. Let’s look at the decision without beating "
                "you up over the result. Which part of your plan will you make easiest "
                "to follow next time?",
                "Trade Review",
                (),
                "Turn the review into one practical process adjustment.",
            )

        if re.fullmatch(
            r"(?:hey|hiya|hello|hi|yo|yoo|what'?s up|what is up|how far)"
            r"(?:\s+(?:bro|sis|there|coach))?[!.? ]*",
            normalized,
        ):
            return CoachReply(
                "Yoo! 👋 What’s good? Are we learning something, reviewing a trade, "
                "or just chatting?",
                "Conversation",
                (),
                "",
            )

        if re.fullmatch(r"(?:thanks|thank you|cheers|appreciate it|got it)[!. ]*", normalized):
            return CoachReply(
                "Anytime — you’ve got this. 🙂",
                "Conversation",
                (),
                "",
            )

        if self._is_loss_message(normalized) and not self._is_stop_out_message(normalized):
            return CoachReply(
                "Ah, that’s frustrating. Take a breath before thinking about another trade. "
                "Did you follow your plan, or did something pull you away from it?",
                "Trade Review",
                (),
                "Review the decision process before judging yourself by one result.",
            )

        if self._is_win_message(normalized):
            return CoachReply(
                "Let’s gooo! 🔥 Nice one. Did you follow your full plan, or did you have "
                "to manage the trade differently?",
                "Trade Review",
                (),
                "A good process matters more than one winning outcome.",
            )

        if self._is_stop_out_message(normalized):
            return CoachReply(
                "Ahh, that’s frustrating. A stop-out doesn’t automatically mean the setup "
                "was bad. Did you follow your plan, or did something pull you away from it?",
                "Trade Review",
                (),
                "A stop-out alone does not prove a mistake; review the process and risk plan.",
            )

        topic = self._detect_topic(normalized)
        if self.is_bos_choch_comparison(normalized):
            return CoachReply(
                "A BOS (Break of Structure) breaks a key swing level in the "
                "direction of the current structure. A CHOCH (Change of Character) "
                "is a meaningful break against the current swing sequence and can "
                "signal a possible shift.\n\n"
                "Bullish Gold example: after lower highs and lower lows, Gold closes "
                "above a prior lower high—possible bullish CHOCH. A later break above "
                "the next swing high can be bullish BOS.\n\n"
                "Bearish Gold example: after higher highs and higher lows, Gold closes "
                "below a prior higher low—possible bearish CHOCH. A later break below "
                "the next swing low can be bearish BOS.\n\n"
                "CHOCH is a warning of a possible change, not a guaranteed reversal. "
                "Which direction are you studying: a bullish shift after lower highs, "
                "or a bearish shift after higher lows?",
                "Market Structure",
                (),
                "Compare structure breaks in context; CHOCH signals possibility, not certainty.",
            )

        if topic == "General SMC" and history and self._looks_like_follow_up(text):
            previous = history[0]
            previous_topic = str(previous.get("detected_topic") or "General SMC")
            if previous_topic not in {
                "General SMC",
                "Conversation",
                "Outside coaching scope",
            }:
                reply = self._continue_conversation(text, previous_topic)
                return CoachReply(
                    reply,
                    previous_topic,
                    (),
                    f"Continue the member's recent discussion about {previous_topic}.",
                )

        if self._is_direct_entry_request(normalized):
            return CoachReply(
                "I can’t see live prices or your chart, so I won’t guess at an entry. "
                "What’s the POI and confirmation you’re seeing?",
                "Setup Review",
                (),
                "Do not make a trade decision from an unseen chart or an unverified signal.",
            )

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
                "and reaction checks your plan requires. Did price take liquidity and then "
                "show a planned confirmation?",
                topic,
                mistakes,
                "Treat an FVG as an area to watch; wait for planned confirmation and a retest.",
            )

        if topic in self._topic_guides:
            explanation, check_question = self._topic_guides[topic]
            response = f"Think of it this way: {explanation}\n\n{check_question}"
            if mistakes:
                response += "\n\nFrom what you wrote, review: " + "; ".join(mistakes) + "."
            if profile.get("latest_assessment_score") is not None and int(
                profile["latest_assessment_score"]
            ) <= 5:
                response = "Let’s keep it simple. " + response
            if profile.get("weakest_topic") == topic:
                response += (
                    f"\n\nThis is one of your current review topics, so it’s a good "
                    "one to practise slowly."
                )
            learning_goal = str(profile.get("learning_goal") or "").strip()
            if learning_goal and self._goal_mentions_topic(learning_goal, topic):
                response += (
                    f"\n\nThat connects to your current focus on {learning_goal}."
                )
            return CoachReply(
                response,
                topic,
                mistakes,
                explanation,
            )

        if mistakes:
            reply = self._review_feedback(topic, mistakes)
            recurring = self._recurring_mistakes(mistakes, history)
            if recurring:
                return CoachReply(
                    reply.response
                    + "\n\nYou’ve mentioned this before too—no judgment. It may help "
                    "to make that rule extra clear in your checklist.",
                    reply.detected_topic,
                    reply.mistakes,
                    reply.lesson_learned,
                )
            return reply

        if self._looks_like_social_message(normalized):
            return CoachReply(
                "I hear you. Hope things ease up a bit. If you want to talk it through, "
                "I’m here.",
                "Conversation",
                (),
                "",
            )

        if self._is_explicitly_unrelated(normalized):
            return CoachReply(
                "I don’t have reliable information for that, so I don’t want to guess. "
                "I can help with SMC concepts, trading-process questions, or reviewing "
                "a decision you’ve already made.",
                "Outside coaching scope",
                (),
                "",
            )

        if topic != "General SMC":
            return CoachReply(
                f"I’m with you on {topic}. What part feels unclear right now?",
                topic,
                (),
                "",
            )

        return CoachReply(
            "I’m not sure what you mean yet. Can you tell me a little more about what "
            "you’re asking?",
            topic,
            (),
            "",
        )

    @staticmethod
    def _is_loss_message(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:i\s+)?(?:lost|took a loss|another loss|losing trade|"
                r"had a loss|blew the account|bad trade|rough day)\b",
                text,
            )
        )

    @staticmethod
    def _is_win_message(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:hit (?:my )?(?:tp|take profit)|hit tp|closed in profit|"
                r"took profit|profitable trade|won (?:a )?trade)\b",
                text,
            )
        )

    @staticmethod
    def _is_direct_entry_request(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:should i|can i|is it time to)\s+(?:buy|sell|enter|short|long)\b"
                r"|\b(?:buy|sell)\s+(?:gold|xauusd|btc|eurusd|now)\s*\??$",
                text,
            )
        )

    @staticmethod
    def _looks_like_follow_up(text: str) -> bool:
        return len(text.split()) <= 12 and not RuleBasedCoachService._contains_any(
            text.casefold(),
            ("what is", "what's", "define", "explain", "teach me", "should i"),
        )

    @staticmethod
    def is_bos_choch_comparison(text: str) -> bool:
        comparison = re.search(
            r"\b(?:difference|compare|versus|vs\.?|distinguish)\b", text
        )
        has_bos = re.search(r"\b(?:bos|break of structure)\b", text)
        has_choch = re.search(r"\b(?:choch|change of character)\b", text)
        return bool(comparison and has_bos and has_choch)

    @staticmethod
    def _continue_conversation(text: str, topic: str) -> str:
        if topic == "CHoCH":
            return (
                f"Got it — you’re pointing to {text}. For a CHoCH, check whether that "
                "was a meaningful swing and whether price closed through it with intent. "
                "Did you get a close beyond the level?"
            )
        if topic in {"FVG / IFVG", "Order Blocks", "POI"}:
            return (
                f"Got it: {text}. That helps pin down the area you’re watching. "
                "What did price do when it reached the zone?"
            )
        return (
            f"Got it — {text}. That adds context to your {topic} question. "
            "What did price do next?"
        )

    @staticmethod
    def _looks_like_social_message(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:tired|stressed|rough|busy|excited|nervous|scared|"
                r"not feeling great|long day)\b",
                text,
            )
        )

    @staticmethod
    def _is_explicitly_unrelated(text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:weather|football|soccer|movie|recipe|restaurant|"
                r"politics|celebrity|homework|travel plans)\b",
                text,
            )
        )

    @staticmethod
    def _recurring_mistakes(
        mistakes: tuple[str, ...], history: list[dict[str, Any]]
    ) -> tuple[str, ...]:
        previous = {
            item.strip()
            for entry in history
            for item in str(entry.get("mistakes_identified") or "").splitlines()
            if item.strip()
        }
        return tuple(mistake for mistake in mistakes if mistake in previous)

    @classmethod
    def _goal_mentions_topic(cls, goal: str, topic: str) -> bool:
        normalized_goal = goal.casefold()
        if topic.casefold() in normalized_goal:
            return True
        for known_topic, aliases in cls._topic_aliases:
            if known_topic == topic:
                return any(alias in normalized_goal for alias in aliases)
        return False

    @classmethod
    def _detect_topic(cls, text: str) -> str:
        for topic, aliases in cls._topic_aliases:
            if cls._contains_any(text, aliases):
                return topic
        return "General SMC"

    @classmethod
    def detect_topic(cls, text: str) -> str:
        """Public local keyword classifier used before any replaceable AI provider."""
        return cls._detect_topic(" ".join(text.split()).casefold())

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
            r"\bentered?\s+(?:too\s+early|before\s+the\s+planned\s+trigger)\b",
            text,
        ):
            mistakes.append("Entry may have been earlier than the planned trigger")
        if re.search(
            r"\b(?:afraid|fear)\s+of\s+missing\s+(?:the\s+)?(?:move|trade|setup)\b"
            r"|\bfomo\b",
            text,
        ):
            mistakes.append("Fear of missing out may have influenced the decision")
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


def ai_evaluate_answer(
    message: str,
    service: CoachService,
    *,
    history: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> CoachReply:
    """Provider seam; this version delegates to a local deterministic service."""
    return service.evaluate(
        message,
        history=history,
        profile=profile,
        request_id=request_id,
    )
