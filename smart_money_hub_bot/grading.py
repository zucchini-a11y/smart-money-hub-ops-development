"""Rule-based written-answer evaluation seam; no external AI service is used."""

import re
from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True)
class WrittenAnswerEvaluation:
    score: int
    maximum_score: int
    matched_concepts: tuple[str, ...]
    missing_concepts: tuple[str, ...]
    feedback: str


class WrittenAnswerEvaluator(Protocol):
    def evaluate(
        self, answer: str, expected_concepts: Sequence[str]
    ) -> WrittenAnswerEvaluation: ...


class RuleBasedWrittenAnswerEvaluator:
    """Conservative keyword rubric that can later be replaced behind this interface."""

    def evaluate(
        self, answer: str, expected_concepts: Sequence[str]
    ) -> WrittenAnswerEvaluation:
        normalized_answer = _normalize(answer)
        matched: list[str] = []
        missing: list[str] = []

        for concept in expected_concepts:
            normalized_concept = _normalize(concept)
            if normalized_concept and normalized_concept in normalized_answer:
                matched.append(concept)
            else:
                missing.append(concept)

        score = len(matched)
        if not expected_concepts:
            feedback = "No grading concepts were configured for this answer."
        elif not answer.strip():
            feedback = "Add a short explanation before submitting your answer."
        elif not missing:
            feedback = "Your answer includes all of the key concepts in this rubric."
        elif matched:
            feedback = "Your answer includes some key concepts; review the missing points."
        else:
            feedback = "Your answer did not include the key points in this rubric."

        return WrittenAnswerEvaluation(
            score=score,
            maximum_score=len(expected_concepts),
            matched_concepts=tuple(matched),
            missing_concepts=tuple(missing),
            feedback=feedback,
        )


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
