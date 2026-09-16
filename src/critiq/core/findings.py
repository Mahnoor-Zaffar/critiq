from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from critiq.core.policy import Category, Severity


class FindingSource(StrEnum):
    STATIC = "static"
    LLM = "llm"


@dataclass(slots=True)
class Finding:
    """A single review finding. The unit emitted by reviewers."""

    category: Category
    file_path: str
    title: str
    explanation: str
    evidence: str
    recommendation: str
    severity: Severity
    confidence: float  # 0.0 - 1.0
    line_start: int | None = None
    line_end: int | None = None
    source: FindingSource = FindingSource.LLM

    def passes_policy(self, policy) -> bool:
        if not policy.allows_category(self.category):
            return False
        if self._rank(self.severity) < self._rank(policy.severity_threshold):
            return False
        if self.confidence < policy.confidence_threshold:
            return False
        return True

    @staticmethod
    def _rank(severity: Severity) -> int:
        return {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
        }[severity]


@dataclass(slots=True)
class ReviewComment:
    """Portable line comment used to render GitHub comments."""

    file_path: str
    body: str
    start_line: int | None = None
    end_line: int | None = None
    finding: Finding | None = None


@dataclass(slots=True)
class ReviewResult:
    """Output of the pipeline before posting to GitHub."""

    decision: str = "COMMENT"
    risk: str = ""
    summary: str = ""
    comments: list[ReviewComment] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
