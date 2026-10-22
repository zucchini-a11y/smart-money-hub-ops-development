"""Research-provider seam; this bot has no runtime web-search provider configured."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResearchResult:
    status: str
    message: str
    sources: tuple[str, ...] = ()


class ResearchProvider(Protocol):
    def research(self, question: str) -> ResearchResult: ...


class UnavailableResearchProvider:
    """Explicit no-op so the application never claims that research occurred."""

    def research(self, question: str) -> ResearchResult:
        del question
        return ResearchResult(
            "awaiting_research",
            "No automated web research provider is configured. Research this question "
            "manually and add source links before drafting an answer.",
        )
