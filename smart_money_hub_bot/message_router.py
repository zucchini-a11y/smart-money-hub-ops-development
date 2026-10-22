"""Route Coach messages through simple intent handling, approved knowledge, and fallback coaching."""

import logging
import random
import re
import uuid
from dataclasses import dataclass
from typing import Any

from .coach import (
    CoachProviderError,
    CoachReply,
    CoachService,
    RuleBasedCoachService,
    ai_evaluate_answer,
)
from .knowledge_base import find_approved_answer
from .question_detection import QuestionAssessment, detect_member_question

logger = logging.getLogger(__name__)

_DIRECT_EDUCATION_START = re.compile(
    r"^(?:what is|what are|define|teach me|explain|compare|difference between)\b",
    re.I,
)
_EXPLICIT_FOLLOW_UP_START = re.compile(
    r"^(?:what about|how about|and then|then|so|in that case|"
    r"does that|would that|is that|what does that mean|why did you|"
    r"explain (?:that|it|this)|say more about (?:that|it|this)|"
    r"based on that)\b",
    re.I,
)
_BRIEF_FOLLOW_UP_QUESTION = re.compile(
    r"^(?:why|how|which one|what next|what then|and why)[?! .]*$",
    re.I,
)


@dataclass(frozen=True)
class RoutedCoachMessage:
    intent: str
    reply: CoachReply
    assessment: QuestionAssessment | None
    approved_item: dict[str, Any] | None = None
    response_path: str = "local_response"
    request_id: str = ""


class CoachMessageRouter:
    """Keyword-first router with an injectable coach provider and SQLite repository."""

    def __init__(
        self,
        coach_service: CoachService,
        store: Any,
        fallback_service: CoachService | None = None,
    ) -> None:
        self.coach_service = coach_service
        self.fallback_service = fallback_service or RuleBasedCoachService()
        self.store = store
        self._last_simple_reply: dict[tuple[int, str], str] = {}

    def route(
        self,
        telegram_id: int,
        message: str,
        *,
        history: list[dict[str, Any]] | None = None,
        profile: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> RoutedCoachMessage:
        if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
            request_id = uuid.uuid4().hex
        simple_intent, greeting = _simple_intent(message)
        if simple_intent:
            response = self._varied_reply(telegram_id, simple_intent, greeting)
            return self._routed(
                simple_intent,
                CoachReply(response, "Conversation", (), ""),
                None,
                "local_response",
                request_id=request_id,
            )

        context_history, context_profile = _relevant_conversation_context(
            message, history, profile
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
            return self._routed(
                "approved_knowledge",
                CoachReply(
                    str(approved_item["approved_answer"]),
                    topic,
                    (),
                    "Answered with administrator-approved knowledge.",
                ),
                assessment,
                "approved_knowledge",
                approved_item=approved_item,
                request_id=request_id,
            )

        if assessment and assessment.needs_research:
            reply = ai_evaluate_answer(
                message,
                self.fallback_service,
                history=context_history,
                profile=context_profile,
                request_id=request_id,
            )
            return self._routed(
                "question",
                self._needs_review_reply(reply),
                assessment,
                "local_response",
                request_id=request_id,
            )

        response_path = "local_response"
        try:
            reply = ai_evaluate_answer(
                message,
                self.coach_service,
                history=context_history,
                profile=context_profile,
                request_id=request_id,
            )
            if (
                getattr(self.coach_service, "diagnostic_response_path", None)
                == "gemini_success"
            ):
                response_path = "gemini_success"
        except CoachProviderError as error:
            logger.warning(
                "Coach provider failed (kind=%s, http_status=%s, elapsed_ms=%s, "
                "google_code=%s, google_status=%s, google_message=%s, headers=%s); "
                "using local fallback. request_id=%s.",
                error.failure_kind,
                error.status_code,
                error.elapsed_ms,
                error.provider_code,
                error.provider_status,
                error.provider_message,
                error.response_headers,
                request_id,
            )
            reply = ai_evaluate_answer(
                message,
                self.fallback_service,
                history=context_history,
                profile=context_profile,
                request_id=request_id,
            )
            response_path = "fallback"
        if assessment and reply.detected_topic != topic:
            assessment = detect_member_question(message, reply.detected_topic) or assessment
        if reply.requires_review:
            response_path = "fallback"
            if assessment is None:
                assessment = detect_member_question(message, reply.detected_topic)
            if assessment:
                from dataclasses import replace

                assessment = replace(
                    assessment,
                    confidence="low",
                    review_reason="The Coach could not provide a reliable answer.",
                )
                reply = self._needs_review_reply(reply)
            else:
                reply = ai_evaluate_answer(
                    message,
                    self.fallback_service,
                    history=context_history,
                    profile=context_profile,
                    request_id=request_id,
                )
        return self._routed(
            "question" if assessment else "coaching",
            reply,
            assessment,
            response_path,
            request_id=request_id,
        )

    @staticmethod
    def _routed(
        intent: str,
        reply: CoachReply,
        assessment: QuestionAssessment | None,
        response_path: str,
        *,
        approved_item: dict[str, Any] | None = None,
        request_id: str,
    ) -> RoutedCoachMessage:
        # Do not log message text, response text, member IDs, or usernames.
        logger.info("Coach response path=%s. request_id=%s.", response_path, request_id)
        return RoutedCoachMessage(
            intent,
            reply,
            assessment,
            approved_item,
            response_path,
            request_id,
        )

    @staticmethod
    def _needs_review_reply(reply: CoachReply) -> CoachReply:
        return CoachReply(
            "I don’t have a vetted answer for this yet, so I won’t guess. "
            "I’ve flagged the question for administrator review. "
            "Any answer added to my knowledge will be checked and approved first.",
            reply.detected_topic,
            reply.mistakes,
            reply.lesson_learned,
            requires_review=True,
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


def _relevant_conversation_context(
    message: str,
    history: list[dict[str, Any]] | None,
    profile: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep prior turns for clear follow-ups, not self-contained questions."""
    if not history:
        return [], {}

    normalized = " ".join(message.split()).strip()
    if _EXPLICIT_FOLLOW_UP_START.match(normalized):
        return history[:1], profile or {}
    if _DIRECT_EDUCATION_START.match(normalized):
        return [], {}

    previous_response = str(history[0].get("coach_response") or "").rstrip()
    if previous_response.endswith("?") and _BRIEF_FOLLOW_UP_QUESTION.fullmatch(
        normalized
    ):
        return history[:1], profile or {}
    is_short_answer_to_coach = (
        previous_response.endswith("?")
        and len(normalized.split()) <= 12
        and not normalized.endswith("?")
    )
    if is_short_answer_to_coach:
        return history[:1], profile or {}

    return [], {}
