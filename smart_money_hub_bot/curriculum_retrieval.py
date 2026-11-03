"""Small, provenance-aware retrieval over curriculum already in the bot."""

from __future__ import annotations

import re
from typing import Any

from .course_materials import COURSE_DOCUMENTS
from .education import EDUCATION
from .knowledge_base import question_similarity, question_tokens

_EPISODE_QUERY = re.compile(r"\bepisode\s*#?\s*0*(\d{1,3})\b", re.IGNORECASE)


def requested_episode_number(question: str) -> int | None:
    """Return an explicitly requested episode number, if one is present."""
    match = _EPISODE_QUERY.search(question or "")
    return int(match.group(1)) if match else None


def retrieve_curriculum_context(
    question: str, *, limit: int = 3
) -> list[dict[str, Any]]:
    """Retrieve relevant in-app lessons and source-labeled uploaded course material."""
    query_tokens = question_tokens(question)
    if not query_tokens:
        return []

    candidates: list[tuple[float, dict[str, str]]] = []
    for key, (title, content) in EDUCATION.items():
        resource_text = f"{key.replace('_', ' ')} {title} {content}"
        resource_tokens = question_tokens(resource_text)
        shared = query_tokens & resource_tokens
        if not shared:
            continue

        coverage = len(shared) / len(query_tokens)
        similarity = question_similarity(question, resource_text)
        title_similarity = question_similarity(question, f"{key} {title}")
        score = coverage * 0.65 + similarity * 0.2 + title_similarity * 0.15
        candidates.append(
            (
                score,
                {
                    "source": "Smart Money Hub Learn menu",
                    "source_type": "built_in_lesson_card",
                    "title": title,
                    "content": content,
                },
            )
        )

    for document in COURSE_DOCUMENTS:
        resource_text = (
            f"{document['title']} {document['search_terms']} {document['content']}"
        )
        resource_tokens = question_tokens(resource_text)
        shared = query_tokens & resource_tokens
        if not shared:
            continue

        coverage = len(shared) / len(query_tokens)
        similarity = question_similarity(question, resource_text)
        title_similarity = question_similarity(question, document["title"])
        score = coverage * 0.65 + similarity * 0.2 + title_similarity * 0.15
        candidates.append((score, dict(document)))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [
        resource
        for score, resource in candidates[: max(1, min(limit, 5))]
        if score >= 0.18
    ]


def episode_unavailable_reply(
    episode_number: int, related_lessons: list[dict[str, Any]]
) -> str:
    """Explain the source gap and, when possible, offer a clearly separate lesson."""
    number = f"{episode_number:02d}"
    response = (
        f"I don’t have the actual Episode {number} lesson indexed, so I can’t "
        f"accurately say what it covered. "
    )
    if related_lessons:
        lesson = related_lessons[0]
        title = " ".join(str(lesson.get("title") or "").split())[:100]
        content = " ".join(str(lesson.get("content") or "").split())[:900]
        if title and content:
            source = " ".join(str(lesson.get("source") or "").split())[:100]
            pages = " ".join(str(lesson.get("pages") or "").split())[:30]
            provenance = f" from {source}" if source else ""
            if pages:
                provenance += f", pages {pages}"
            response += (
                f"I can offer related course material, “{title}”{provenance} "
                f"(not a summary of Episode {number}): {content} "
            )
    response += (
        "Share the episode text or a screenshot and I’ll explain that exact material."
    )
    return response


def curriculum_source_summary() -> dict[str, int]:
    """Return counts for real in-app lesson cards, with no inferred episodes."""
    return {
        "lesson_cards": len(EDUCATION),
        "uploaded_course_documents": len(COURSE_DOCUMENTS),
        "episode_records": 0,
        "external_documents": 0,
    }
