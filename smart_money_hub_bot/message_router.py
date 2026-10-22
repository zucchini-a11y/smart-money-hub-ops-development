"""Route Coach messages through simple intent handling, approved knowledge, and fallback coaching."""

import logging
import random
import re
from dataclasses import dataclass
from typing import Any

from .coach import CoachReply, CoachService, RuleBasedCoachService, ai_evaluate_answer
from .knowledge_base import find_approved_answer
from .question_detection import QuestionAssessment, detect_member_question

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutedCoachMessage:
    intent: str
    reply: CoachReply
    assessment: QuestionAssessment | None
    approved_item: dict[str, Any] | None = None


class CoachMessageRouter:
    """Keyword-first router with an injectable coach provider and SQLite repository."""

    def __init__(self, coach_service: CoachService, store: Any) -> None:
        self.coach_service = coach_service
        self.store = store
        self._last_simple_reply: dict[tuple[int, str], str] = {}

    def route(
        self,
        telegram_id: int,
        message: str,
        *,
        history: list[dict[str, Any]] | None = None,
        profile: dict[str, Any] | None = None,
    ) -> RoutedCoachMessage:
        simple_intent, greeting = _simple_intent(message)
        if simple_intent:
            response = self._varied_reply(telegram_id, simple_intent, greeting)
            return RoutedCoachMessage(
                simple_intent,
                CoachReply(response, "Conversation", (), ""),
                None,
            )

        # Topic identification and approved-knowledge lookup are local and run
        # before the replaceable Coach provider is asked to draft a reply.
        topic = RuleBasedCoachService.detect_topic(message)
        assessment = detect_member_question(message, topic)
        approved_item = None
        if assessment:
            try:
                approved_item = find_approved_answer(
                    message,
                    assessment.topic,
                    self.store.approved_knowledge_items(),
                )
            except Exception:
                # The regular Coach still works if a saved-knowledge read fails.
                logger.exception("Could not retrieve approved Coach knowledge.")
                approved_item = None
        if approved_item:
            return RoutedCoachMessage(
                "approved_knowledge",
                CoachReply(
                    str(approved_item["approved_answer"]),
                    topic,
                    (),
                    "Answered with administrator-approved knowledge.",
                ),
                assessment,
                approved_item,
            )

        reply = ai_evaluate_answer(
            message,
            self.coach_service,
            history=history,
            profile=profile,
        )
        if assessment and reply.detected_topic != topic:
            assessment = detect_member_question(message, reply.detected_topic) or assessment
        if assessment and assessment.needs_research:
            reply = CoachReply(
                "I don’t have a vetted answer for this yet, so I won’t guess. "
                "I’ve flagged the question for administrator review. "
                "Any answer added to my knowledge will be checked and approved first.",
                reply.detected_topic,
                reply.mistakes,
                reply.lesson_learned,
            )
        return RoutedCoachMessage(
            "question" if assessment else "coaching",
            reply,
            assessment,
        )

    def _varied_reply(
        self, telegram_id: int, intent: str, greeting: str
    ) -> str:
        options = _SIMPLE_REPLIES[intent][greeting]
        previous = self._last_simple_reply.get((telegram_id, intent))
        choices = [response for response in options if response != previous] or options
        response = random.choice(choices)
        self._last_simple_reply[(telegram_id, intent)] = response
        return response


_SIMPLE_REPLIES: dict[str, dict[str, tuple[str, ...]]] = {
    "greeting": {
        "morning": (
            "Good morning! What can I help you with?",
            "Morning! What would you like to talk about?",
            "Good morning. How can I help today?",
        ),
        "afternoon": (
            "Good afternoon! What can I help you with?",
            "Afternoon! What would you like to work through?",
            "Good afternoon. How can I help today?",
        ),
        "evening": (
            "Good evening! What can I help you with?",
            "Evening! What would you like to talk about?",
            "Good evening. How can I help today?",
        ),
        "general": (
            "Hey! How can I help?",
            "Hi there! What can I help you with?",
            "Hello! What would you like to talk about?",
            "Hey, good to hear from you. What can I help with?",
        ),
    },
    "thanks": {
        "default": (
            "You’re welcome. Glad that helped.",
            "Anytime. Happy to help.",
            "You got it. Reach out whenever you need.",
        )
    },
    "farewell": {
        "default": (
            "Bye for now. Take care.",
            "See you next time. Take care.",
            "Talk soon. Have a good one.",
        )
    },
    "acknowledgement": {
        "default": (
            "Got it.",
            "Alright, sounds good.",
            "Okay. No rush.",
            "Understood.",
        )
    },
}

_GREETING = re.compile(
    r"^(?:hi|hello|hey|hiya|yo|yoo|good morning|morning|good afternoon|"
    r"afternoon|good evening|evening|what'?s up|what is up|how far)"
    r"(?:\s+(?:bro|sis|there|coach))?[!.? ]*$",
    re.I,
)
_THANKS = re.compile(
    r"^(?:thanks?(?:\s+(?:a lot|so much|very much))?|thank you"
    r"(?:\s+(?:so much|very much))?|cheers|appreciate it)[!. ]*$",
    re.I,
)
_FAREWELL = re.compile(
    r"^(?:bye|goodbye|later|see you(?: later)?|talk later|catch you later|"
    r"take care|good night)(?:\s+(?:bro|sis|there))?[!. ]*$",
    re.I,
)
_ACKNOWLEDGEMENT = re.compile(
    r"^(?:ok|okay|alright|all right|got it|understood|sure|sounds good|"
    r"noted|fine by me|makes sense|yeah|yep|yup|gotcha|perfect)[!. ]*$",
    re.I,
)


def _simple_intent(message: str) -> tuple[str | None, str]:
    text = " ".join(message.replace("’", "'").replace("‘", "'").split()).strip()
    if not text:
        return None, "default"
    if _GREETING.fullmatch(text):
        lowered = text.casefold()
        if "morning" in lowered:
            return "greeting", "morning"
        if "afternoon" in lowered:
            return "greeting", "afternoon"
        if "evening" in lowered:
            return "greeting", "evening"
        return "greeting", "general"
    if _THANKS.fullmatch(text):
        return "thanks", "default"
    if _FAREWELL.fullmatch(text):
        return "farewell", "default"
    if _ACKNOWLEDGEMENT.fullmatch(text):
        return "acknowledgement", "default"
    return None, "default"
