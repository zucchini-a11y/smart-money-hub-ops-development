"""Validation helpers for administrator-authored knowledge drafts and research notes."""

import re
from datetime import date
from urllib.parse import urlparse


def validate_answer_draft(answer: str) -> str:
    clean = " ".join(answer.split()).strip()
    if len(clean) < 40:
        raise ValueError("Please write an answer of at least 40 characters.")
    if len(clean) > 3000:
        raise ValueError("Keep the proposed answer under 3,000 characters.")
    return clean


def parse_research_material(text: str) -> dict[str, str]:
    """Parse HTTPS source lines and optional NOTE, CONFLICT, and REVIEW_BY lines."""
    sources: list[str] = []
    notes: list[str] = []
    review_after = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("NOTE:"):
            notes.append(line[5:].strip())
            continue
        if line.upper().startswith("CONFLICT:"):
            notes.append("Conflicting information: " + line[9:].strip())
            continue
        if line.upper().startswith("REVIEW_BY:"):
            candidate = line.split(":", 1)[1].strip()
            try:
                review_after = date.fromisoformat(candidate).isoformat()
            except ValueError:
                raise ValueError("Use REVIEW_BY: YYYY-MM-DD for a review date.") from None
            continue
        parsed = urlparse(line)
        if parsed.scheme != "https" or not parsed.netloc or re.search(r"\s", line):
            raise ValueError(
                "Use one HTTPS source URL per line. Add context as NOTE: text, "
                "CONFLICT: text, or REVIEW_BY: YYYY-MM-DD."
            )
        if line not in sources:
            sources.append(line)
    if not sources:
        raise ValueError("Add at least one HTTPS source before saving research notes.")
    return {
        "source_urls": "\n".join(sources),
        "research_notes": "\n".join(notes),
        "review_after": review_after,
    }
