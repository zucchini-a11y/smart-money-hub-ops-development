"""Deterministic multiple-choice scoring, independent from the Telegram layer."""

from dataclasses import dataclass
from typing import Sequence

from .questions import QUESTIONS


@dataclass(frozen=True)
class IncorrectAnswer:
    question_number: int
    topic: str
    selected_answer: str
    correct_answer: str
    explanation: str


@dataclass(frozen=True)
class AssessmentResult:
    score: int
    total: int
    percentage: int
    incorrect_answers: tuple[IncorrectAnswer, ...]


def grade_answers(answers: Sequence[int]) -> AssessmentResult:
    """Grade one option index per question and return useful review details."""
    if len(answers) != len(QUESTIONS):
        raise ValueError(
            f"Expected {len(QUESTIONS)} answers, received {len(answers)}."
        )

    score = 0
    incorrect: list[IncorrectAnswer] = []

    for question_number, (question, selected_index) in enumerate(
        zip(QUESTIONS, answers), start=1
    ):
        if not isinstance(selected_index, int) or not 0 <= selected_index < len(
            question.options
        ):
            raise ValueError(
                f"Answer {question_number} must be an option index from 0 to 3."
            )

        if selected_index == question.correct_index:
            score += 1
            continue

        incorrect.append(
            IncorrectAnswer(
                question_number=question_number,
                topic=question.topic,
                selected_answer=question.options[selected_index],
                correct_answer=question.options[question.correct_index],
                explanation=question.explanation,
            )
        )

    total = len(QUESTIONS)
    return AssessmentResult(
        score=score,
        total=total,
        percentage=round(score / total * 100),
        incorrect_answers=tuple(incorrect),
    )