"""Member feedback definitions for Coach answers."""

REACTIONS = {"helpful", "unhelpful", "unclear"}


def requires_review(reaction: str) -> bool:
    return reaction in {"unhelpful", "unclear"}
