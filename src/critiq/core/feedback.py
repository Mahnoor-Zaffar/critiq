from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class FeedbackSignal(StrEnum):
    """A developer's reaction to a posted finding."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class FeedbackStats:
    """Aggregate developer feedback for one finding category."""

    category: str
    total: int
    accepted: int
    resolved: int

    @property
    def accept_rate(self) -> float:
        """Fraction of signals that treated the finding as valid."""
        if self.total == 0:
            return 0.0
        return (self.accepted + self.resolved) / self.total


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


class ConfidenceCalibrator:
    """Adjusts finding confidence from a category's historical feedback.

    Confidence is nudged toward the observed acceptance rate (accepted +
    resolved, i.e. findings the team treated as valid). The nudge is bounded by
    MAX_DELTA and scales with evidence: it grows with the number of gathered
    signals and saturates at SATURATION, so a handful of reactions never
    overrides the reviewer's own judgment while an established pattern does.
    """

    BASELINE = 0.5
    MAX_DELTA = 0.10
    SATURATION = 15

    def __init__(self, stats: Mapping[str, FeedbackStats]) -> None:
        self._stats = dict(stats)

    def calibrate(self, confidence: float, category: str) -> float:
        stats = self._stats.get(category)
        if stats is None or stats.total == 0:
            return confidence
        evidence = min(1.0, stats.total / self.SATURATION)
        delta = (stats.accept_rate - self.BASELINE) * 2 * self.MAX_DELTA * evidence
        return self._clamp(round(confidence + delta, 4))

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
