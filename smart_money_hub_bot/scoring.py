"""Deterministic multiple-choice scoring, independent from the Telegram layer."""

from dataclasses import dataclass
from typing import Sequence

from .questions import QUESTIONS


@dataclass(frozen=True)
class AnswerRecord:
    question_number: int
    topic: str
    selected_answer: str
    correct_answer: str
    is_correct: bool
    explanation: str


@dataclass(frozen=True)
class AssessmentResult:
    score: int
    total: int
    percentage: int
    answers: tuple[AnswerRecord, ...]
    incorrect_answers: tuple[AnswerRecord, ...]
    strong_areas: tuple[str, ...]
    weak_areas: tuple[str, ...]


def grade_answers(answers: Sequence[int]) -> AssessmentResult:
    """Grade one option index per question and return useful review details."""
    if len(answers) != len(QUESTIONS):
        raise ValueError(
            f"Expected {len(QUESTIONS)} answers, received {len(answers)}."
        )

    score = 0
    records: list[AnswerRecord] = []
    topic_results: dict[str, list[bool]] = {}

    for question_number, (question, selected_index) in enumerate(
        zip(QUESTIONS, answers), start=1
    ):
        if not isinstance(selected_index, int) or not 0 <= selected_index < len(
            question.options
        ):
            raise ValueError(
                f"Answer {question_number} must be an option index from 0 to 3."
            )

        is_correct = selected_index == question.correct_index
        topic_results.setdefault(question.topic, []).append(is_correct)
        if is_correct:
            score += 1
        records.append(
            AnswerRecord(
                question_number=question_number,
                topic=question.topic,
                selected_answer=question.options[selected_index],
                correct_answer=question.options[question.correct_index],
                is_correct=is_correct,
                explanation=question.explanation if not is_correct else "",
            )
        )

    total = len(QUESTIONS)
    incorrect = tuple(answer for answer in records if not answer.is_correct)
    return AssessmentResult(
        score=score,
        total=total,
        percentage=round(score / total * 100),
        answers=tuple(records),
        incorrect_answers=incorrect,
        strong_areas=tuple(
            topic for topic, values in topic_results.items() if all(values)
        ),
        weak_areas=tuple(
            topic for topic, values in topic_results.items() if not all(values)
        ),
    )