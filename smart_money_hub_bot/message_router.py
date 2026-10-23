"""Route Coach messages through simple intent handling, approved knowledge, and fallback coaching."""

import logging
import random
import re
import uuid
from dataclasses import dataclass, replace
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
        is_admin = bool(profile and profile.get("is_admin") is True)
        simple_intent, greeting = _simple_intent(message)
        if simple_intent:
            response = self._varied_reply(
                telegram_id, simple_intent, greeting, is_admin=is_admin
            )
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
            approved_answer = str(approved_item["approved_answer"])
            if is_admin:
                approved_answer = f"Certainly, CEO — {approved_answer}"
            return self._routed(
                "approved_knowledge",
                CoachReply(
                    approved_answer,
                    topic,
                    (),
                    "Answered with administrator-approved knowledge.",
                ),
                assessment,
                "approved_knowledge",
                approved_item=approved_item,
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
                "google_code=%s, google_status=%s, google_message=%s, headers=%s, "
                "rejection_category=%s); using local fallback. request_id=%s.",
                error.failure_kind,
                error.status_code,
                error.elapsed_ms,
                error.provider_code,
                error.provider_status,
                error.provider_message,
                error.response_headers,
                error.rejection_category,
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
        if assessment and assessment.needs_research and not reply.requires_review:
            if response_path == "gemini_success":
                assessment = replace(
                    assessment,
                    confidence="high",
                    review_reason="Answered by the configured Coach provider.",
                )
            else:
                reply = self._needs_review_reply(
                    reply, topic=assessment.topic
                )
                response_path = "fallback"
        if reply.requires_review:
            include_ai_note = response_path == "gemini_success"
            response_path = "gemini_review" if include_ai_note else "fallback"
            if assessment is None:
                assessment = detect_member_question(message, reply.detected_topic)
            if assessment:
                assessment = replace(
                    assessment,
                    confidence="low",
                    review_reason="The Coach could not provide a reliable answer.",
                )
                reply = self._needs_review_reply(
                    reply,
                    topic=assessment.topic,
                    include_ai_note=include_ai_note,
                )
            else:
                reply = ai_evaluate_answer(
                    message,
                    self.fallback_service,
                    history=context_history,
                    profile=context_profile,
                    request_id=request_id,
                )
        if is_admin and response_path == "fallback" and not reply.requires_review:
            reply = replace(reply, response=f"Certainly, CEO — {reply.response}")
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
    def _needs_review_reply(
        reply: CoachReply,
        *,
        topic: str | None = None,
        include_ai_note: bool = False,
    ) -> CoachReply:
        review_guidance = {
            "Current Market Information": (
                "I don’t have a live chart or price feed, so I can’t verify the current "
                "move. Share the symbol, timeframe, and chart or price you’re looking at, "
                "and I can explain those details without guessing."
            ),
            "Economic News and Fundamentals": (
                "I can explain what the report measures, but I can’t verify its latest "
                "release here. Share the headline or figures and I’ll help interpret them."
            ),
            "Broker and Platform Questions": (
                "Broker and platform rules can vary or change. Share the platform name "
                "and the wording of the rule—not account details—and I’ll explain the "
                "general terms."
            ),
        }
        guidance = review_guidance.get(
            topic or reply.detected_topic,
            "I couldn’t confirm a dependable answer this time. Narrow it to one term or "
            "share the specific example you want explained, and I’ll take another pass.",
        )
        review_notice = "I’ve sent this to an administrator to check."
        answer = reply.response.strip()
        if include_ai_note and answer:
            response = (
                f"Coach note — not verified yet:\n{answer}\n\n"
                f"{guidance} {review_notice}"
            )
        else:
            response = f"{guidance} {review_notice}"
        return CoachReply(
            response,
            reply.detected_topic,
            reply.mistakes,
            reply.lesson_learned,
            requires_review=True,
        )

    def _varied_reply(
        self, telegram_id: int, intent: str, greeting: str, *, is_admin: bool = False
    ) -> str:
        reply_library = _ADMIN_SIMPLE_REPLIES if is_admin else _SIMPLE_REPLIES
        options = reply_library[intent][greeting]
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
_ADMIN_SIMPLE_REPLIES: dict[str, dict[str, tuple[str, ...]]] = {
    "greeting": {
        "morning": (
            "Good morning, CEO. How may I assist you today?",
            "Good morning, CEO. What can I help you with?",
        ),
        "afternoon": (
            "Good afternoon, CEO. How may I assist you today?",
            "Good afternoon, CEO. What can I help you with?",
        ),
        "evening": (
            "Good evening, CEO. How may I assist you today?",
            "Good evening, CEO. What can I help you with?",
        ),
        "general": (
            "Hello, CEO. How may I assist you today?",
            "Hello, CEO. What can I help you with?",
        ),
    },
    "thanks": {
        "default": (
            "You’re very welcome. I’m glad I could help.",
            "Of course. I’m pleased that was useful.",
        )
    },
    "farewell": {
        "default": (
            "Goodbye. Wishing you a good day.",
            "Take care. I’ll be here if you need further help.",
        )
    },
    "acknowledgement": {
        "default": (
            "Understood.",
            "Certainly. I’ll keep that in mind.",
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
    role_context = {"is_admin": True} if profile and profile.get("is_admin") is True else {}
    if not history:
        return [], role_context

    normalized = " ".join(message.split()).strip()
    if _EXPLICIT_FOLLOW_UP_START.match(normalized):
        return history[:1], {**(profile or {}), **role_context}
    if _DIRECT_EDUCATION_START.match(normalized):
        return [], role_context

    previous_response = str(history[0].get("coach_response") or "").rstrip()
    if previous_response.endswith("?") and _BRIEF_FOLLOW_UP_QUESTION.fullmatch(
        normalized
    ):
        return history[:1], {**(profile or {}), **role_context}
    is_short_answer_to_coach = (
        previous_response.endswith("?")
        and len(normalized.split()) <= 12
        and not normalized.endswith("?")
    )
    if is_short_answer_to_coach:
        return history[:1], {**(profile or {}), **role_context}

    return [], role_context
