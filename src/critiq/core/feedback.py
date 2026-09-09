from __future__ import annotations

from enum import StrEnum


class FeedbackSignal(StrEnum):
    """A developer's reaction to a posted finding."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class ConfidenceAdjuster:
    """Adjusts a finding's confidence based on developer feedback.

    Positive signals (ACCEPTED/RESOLVED) increase confidence; REJECTED decreases it.
    This is the seed of a feedback-learning loop: over time Critiq calibrates what
    reviewers will accept.
    """

    BOOST = 0.05
    PENALTY = 0.10

    def adjust(self, confidence: float, signal: FeedbackSignal) -> float:
        if signal in (FeedbackSignal.ACCEPTED, FeedbackSignal.RESOLVED):
            return self._clamp(round(confidence + self.BOOST, 4))
        if signal == FeedbackSignal.REJECTED:
            return self._clamp(round(confidence - self.PENALTY, 4))
        return confidence

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
