"""Guardrails for human approval of a researched knowledge answer."""


def can_approve(answer: str | None, source_urls: str | None) -> bool:
    return bool((answer or "").strip() and (source_urls or "").strip())


def rejection_status(has_previous_approved_answer: bool) -> str:
    """Rejecting a revision must not remove an already-approved answer."""
    return "approved" if has_previous_approved_answer else "rejected"
