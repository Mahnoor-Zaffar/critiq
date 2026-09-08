from __future__ import annotations

from critiq.core.policy import Severity


class SeverityScorer:
    """Static mapping helpers for severity and confidence."""

    @staticmethod
    def rank(severity: Severity) -> int:
        return {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
        }.get(severity, 1)

    @staticmethod
    def is_below(severity: Severity, threshold: Severity) -> bool:
        return SeverityScorer.rank(severity) < SeverityScorer.rank(threshold)
