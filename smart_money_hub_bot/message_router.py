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
from .curriculum_retrieval import (
    episode_unavailable_reply,
    requested_episode_number,
)
from .knowledge_base import find_approved_answer, question_tokens
from .question_detection import QuestionAssessment, detect_member_question

logger = logging.getLogger(__name__)

_DIRECT_EDUCATION_START = re.compile(
    r"^(?:what is|what are|define|teach me|explain|compare|difference between)\b",
    re.I,
)
_EXPLICIT_FOLLOW_UP_START = re.compile(
    r"^(?:what about|how about|and then|and what|then|so|in that case|"
    r"does that|would that|is that|what does that mean|why did you|"
    r"what should i do(?: now| next)?|what do i do(?: now| next)?|"
    r"what happens(?: now| next| to it| to that)?|"
    r"when will (?:it|that|this|they|the bot|the post)\b|"
    r"will (?:it|that|this|they|the bot|the post)\b|"
    r"should i (?:do|send|post|use|choose) (?:that|it|this|now|next)\b|"
    r"explain (?:that|it|this)|say more about (?:that|it|this)|"
    r"based on that)\b",
    re.I,
)
_BRIEF_FOLLOW_UP_QUESTION = re.compile(
    r"^(?:why|how|which one|what next|what then|and why)[?! .]*$",
    re.I,
)
_EDUCATION_RESOURCE_REQUEST = re.compile(
    r"\b(?:pdfs?|videos?|recordings?|course resources?)\b"
    r".{0,60}\b(?:link|send|share|provide|find|where|show|get|give|need|want|have)\b"
    r"|\b(?:link|send|share|provide|find|where|show|get|give|need|want|have|"
    r"looking for|recommend)\b"
    r".{0,60}\b(?:pdfs?|videos?|recordings?|course resources?)\b",
    re.I,
)


def _education_resources(profile: dict[str, Any] | None) -> list[dict[str, str]]:
    if not profile or not isinstance(profile.get("education_resources_context"), list):
        return []
    resources: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in profile["education_resources_context"][:3]:
        if not isinstance(item, dict):
            continue
        resource_type = str(item.get("resource_type") or "").casefold()
        title = " ".join(str(item.get("title") or "").split())[:160]
        link = str(item.get("message_link") or "").strip()
        if (
            resource_type not in {"pdf", "video"}
            or not title
            or not link.startswith("https://t.me/")
            or len(link) > 400
            or link in seen
        ):
            continue
        seen.add(link)
        resources.append(
            {"resource_type": resource_type, "title": title, "message_link": link}
        )
    return resources


def _education_resource_text(resources: list[dict[str, str]]) -> str:
    if not resources:
        return ""
    lines = [
        "Matching Education-group resources:",
        *[
            f"• {item['resource_type'].upper()}: {item['title']}\n"
            f"  {item['message_link']}"
            for item in resources[:3]
        ],
    ]
    return "\n".join(lines)


def _append_education_resources(
    response: str, resources: list[dict[str, str]]
) -> str:
    missing = [
        item
        for item in resources
        if item["message_link"] not in response
    ]
    if not missing:
        return response
    return f"{response.rstrip()}\n\n{_education_resource_text(missing)}"


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
        resources = _education_resources(profile)
        if _EDUCATION_RESOURCE_REQUEST.search(message):
            if not resources:
                response = (
                    "I don’t have a matching Education-group PDF or video link "
                    "indexed yet. If the admin posts it in the group with a clear "
                    "caption, I can suggest it when someone asks a related question."
                )
                return self._routed(
                    "education_resource_not_indexed",
                    CoachReply(response, "Education group resources", (), ""),
                    None,
                    "local_response",
                    request_id=request_id,
                )
            response = _education_resource_text(resources)
            if is_admin:
                response = f"Certainly, CEO —\n{response}"
            return self._routed(
                "education_resources",
                CoachReply(response, "Education group resources", (), ""),
                None,
                "local_response",
                request_id=request_id,
            )

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

        requested_episode = requested_episode_number(message)
        if (
            requested_episode is not None
            and profile
            and profile.get("episode_source_missing") == requested_episode
        ):
            related_lessons = profile.get("curriculum_context", [])
            if not isinstance(related_lessons, list):
                related_lessons = []
            resources = _education_resources(profile)
            response = _append_education_resources(
                episode_unavailable_reply(requested_episode, related_lessons),
                resources,
            )
            return self._routed(
                "episode_source_unavailable",
                CoachReply(
                    response,
                    "Smart Money Hub curriculum",
                    (),
                    "The requested episode is not present in indexed sources.",
                    requires_review=True,
                ),
                None,
                "curriculum_source_gap",
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
            approved_answer = _append_education_resources(
                approved_answer, resources
            )
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
                self._record_provider_event(
                    feature="coach_text",
                    outcome="success",
                )
        except CoachProviderError as error:
            self._record_provider_event(
                feature="coach_text",
                outcome="failure",
                failure_kind=error.failure_kind,
                http_status=error.status_code,
                provider_status=error.provider_status or "",
            )
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
                )
            else:
                reply = ai_evaluate_answer(
                    message,
                    self.fallback_service,
                    history=context_history,
                    profile=context_profile,
                    request_id=request_id,
                )
        reply = replace(
            reply,
            response=_append_education_resources(reply.response, resources),
        )
        if is_admin and _claims_admin_posting_is_unavailable(message, reply.response):
            reply = replace(
                reply,
                response=(
                    "That earlier limitation was incorrect. I can prepare a private "
                    "preview for the configured Market Analysis channel or Education "
                    "group. Send the complete post and destination, or ask me to use "
                    "your latest lesson. You’ll receive a real preview with buttons. "
                    "Nothing is posted until you tap Approve and then Publish."
                ),
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

    def _record_provider_event(self, **event: Any) -> None:
        recorder = getattr(self.store, "record_coach_provider_event", None)
        if not callable(recorder):
            return
        try:
            recorder(**event)
        except Exception:
            logger.warning("Could not record Coach provider health metadata.")

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
            "I can’t verify the current detail from here. Share the specific source or "
            "example, and I can help interpret it.",
        )
        answer = reply.response.strip()
        response = (
            answer
            if answer and guidance.casefold() in answer.casefold()
            else f"{answer}\n\n{guidance}" if answer else guidance
        )
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
    """Keep a short, connected thread for follow-ups, not new questions."""
    role_context: dict[str, Any] = {}
    if profile and profile.get("is_admin") is True:
        role_context["is_admin"] = True
    if profile and isinstance(profile.get("group_knowledge_context"), list):
        role_context["group_knowledge_context"] = profile["group_knowledge_context"]
    if profile and isinstance(profile.get("curriculum_context"), list):
        role_context["curriculum_context"] = profile["curriculum_context"]
    if profile and isinstance(profile.get("education_resources_context"), list):
        role_context["education_resources_context"] = profile[
            "education_resources_context"
        ]
    if profile and isinstance(profile.get("matching_education_diagram_context"), dict):
        role_context["matching_education_diagram_context"] = profile[
            "matching_education_diagram_context"
        ]
    if profile and isinstance(profile.get("episode_context"), list):
        role_context["episode_context"] = profile["episode_context"]
    if profile and isinstance(profile.get("episode_source_missing"), int):
        role_context["episode_source_missing"] = profile["episode_source_missing"]
    if profile and isinstance(profile.get("learning_goal"), str):
        goal = profile["learning_goal"][:300]
        if question_tokens(message) & question_tokens(goal):
            role_context["learning_goal"] = goal
    if not history:
        return [], role_context

    normalized = " ".join(message.split()).strip()
    previous_response = str(history[0].get("coach_response") or "").rstrip()
    previous_question = str(history[0].get("question") or "").rstrip()
    previous_message = f"{previous_question} {previous_response}".strip()
    current_topic = RuleBasedCoachService.detect_topic(normalized)
    previous_topic = str(history[0].get("detected_topic") or "").strip()
    topic_changed = bool(
        current_topic != "General SMC"
        and previous_topic
        and current_topic.casefold() != previous_topic.casefold()
    )
    is_explicit_follow_up = bool(_EXPLICIT_FOLLOW_UP_START.match(normalized))
    is_brief_follow_up = bool(_BRIEF_FOLLOW_UP_QUESTION.fullmatch(normalized))
    shared_terms = question_tokens(normalized) & question_tokens(previous_message)
    meaningful_shared_terms = shared_terms - {
        "post",
        "bot",
        "message",
        "thing",
        "today",
        "tomorrow",
        "time",
        "help",
        "send",
        "now",
        "next",
    }
    refers_to_prior_point = bool(
        re.search(
            r"\b(?:it|that|this|they|them|there|those|these|one)\b",
            normalized.casefold(),
        )
        and len(normalized.split()) <= 18
    )
    if _DIRECT_EDUCATION_START.match(normalized) and (
        topic_changed
        or (not is_explicit_follow_up and not refers_to_prior_point)
    ):
        return [], role_context
    if (
        is_explicit_follow_up
        or is_brief_follow_up
        or refers_to_prior_point
        or len(meaningful_shared_terms) >= 2
        or (
            len(normalized.split()) <= 4
            and len(meaningful_shared_terms) == 1
        )
    ):
        return _connected_conversation_thread(history), {
            **(profile or {}),
            **role_context,
        }
    is_short_answer_to_coach = (
        previous_response.endswith("?")
        and len(normalized.split()) <= 12
        and not normalized.endswith("?")
    )
    if is_short_answer_to_coach:
        return _connected_conversation_thread(history), {
            **(profile or {}),
            **role_context,
        }

    return [], role_context


def _connected_conversation_thread(
    history: list[dict[str, Any]], *, limit: int = 3
) -> list[dict[str, Any]]:
    """Return recent exchanges linked by topic or by the neighboring turn."""
    if not history:
        return []
    selected = [history[0]]
    for candidate in history[1:limit]:
        newer = selected[-1]
        newer_topic = str(newer.get("detected_topic") or "").strip().casefold()
        candidate_topic = str(candidate.get("detected_topic") or "").strip().casefold()
        same_topic = bool(
            newer_topic
            and candidate_topic
            and newer_topic == candidate_topic
            and newer_topic not in {"conversation", "general"}
        )
        newer_text = " ".join(
            str(newer.get(key) or "") for key in ("question", "coach_response")
        )
        candidate_text = " ".join(
            str(candidate.get(key) or "") for key in ("question", "coach_response")
        )
        shared_terms = question_tokens(newer_text) & question_tokens(candidate_text)
        if same_topic or len(shared_terms) >= 2:
            selected.append(candidate)
        else:
            break
    return selected


def _claims_admin_posting_is_unavailable(message: str, response: str) -> bool:
    """Detect the stale Coach refusal that contradicts admin posting controls."""
    asks_about_posting = bool(
        re.search(r"\b(?:post|publish|send)\b", message, flags=re.IGNORECASE)
    )
    denies_posting = bool(
        re.search(
            r"\b(?:cannot|can't|unable|not able to|do not have the ability to)\b"
            r".{0,80}\b(?:post|publish|send)\b"
            r"|\b(?:copy and paste|copy/paste)\b"
            r".{0,80}\b(?:channel|post|publish)\b",
            response,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    return asks_about_posting and denies_posting
