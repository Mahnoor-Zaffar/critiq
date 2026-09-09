from __future__ import annotations

from dataclasses import dataclass, field

from critiq.ai.evaluation.dataset import EvalFinding
from critiq.core.findings import Finding
from critiq.core.policy import Category

LINE_TOLERANCE = 2


@dataclass(slots=True)
class CaseMetrics:
    case_id: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    useful: int = 0

    @property
    def predicted_total(self) -> int:
        return self.true_positives + self.false_positives

    @property
    def expected_total(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def precision(self) -> float:
        return _ratio(self.true_positives, self.predicted_total)

    @property
    def recall(self) -> float:
        return _ratio(self.true_positives, self.expected_total)

    @property
    def false_positive_rate(self) -> float:
        return _ratio(self.false_positives, self.predicted_total)

    @property
    def useful_rate(self) -> float:
        return _ratio(self.useful, self.predicted_total)


@dataclass(slots=True)
class AggregateMetrics:
    total_predicted: int = 0
    total_expected: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    useful: int = 0
    by_category: dict[Category, CaseMetrics] = field(default_factory=dict)

    def add(self, m: CaseMetrics) -> None:
        self.total_predicted += m.predicted_total
        self.total_expected += m.expected_total
        self.true_positives += m.true_positives
        self.false_positives += m.false_positives
        self.false_negatives += m.false_negatives
        self.useful += m.useful

    @property
    def precision(self) -> float:
        return _ratio(self.true_positives, self.total_predicted)

    @property
    def recall(self) -> float:
        return _ratio(self.true_positives, self.total_expected)

    @property
    def false_positive_rate(self) -> float:
        return _ratio(self.false_positives, self.total_predicted)

    @property
    def useful_rate(self) -> float:
        return _ratio(self.useful, self.total_predicted)


def measure(case_id: str, predicted: list[Finding], expected: list[EvalFinding]) -> CaseMetrics:
    """Match predicted findings to ground-truth expected findings."""
    metrics = CaseMetrics(case_id=case_id)
    available = list(expected)

    for finding in predicted:
        match_idx = _find_available_match(finding, available)
        if match_idx is None:
            metrics.false_positives += 1
            continue
        matched = available.pop(match_idx)
        metrics.true_positives += 1
        if matched.useful:
            metrics.useful += 1

    metrics.false_negatives = len(available)
    return metrics


def _find_available_match(finding: Finding, expected: list[EvalFinding]) -> int | None:
    for idx, exp in enumerate(expected):
        if exp.category != finding.category:
            continue
        if exp.file_path != finding.file_path:
            continue
        if _line_matches(finding.line_start, exp.line_start):
            return idx
    return None


def _line_matches(predicted: int | None, expected: int | None) -> bool:
    if predicted is None:
        return expected is None
    if expected is None:
        return True  # file-level expected: any line is a match
    return abs(predicted - expected) <= LINE_TOLERANCE


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
