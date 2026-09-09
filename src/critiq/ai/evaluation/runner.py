from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from critiq.ai.evaluation.dataset import EvalCase
from critiq.ai.evaluation.metrics import CaseMetrics, measure
from critiq.ai.providers.mock import MockProvider
from critiq.analysis.diff import parse_patch
from critiq.core.findings import Finding
from critiq.core.policy import Category, ReviewPolicy
from critiq.pipeline import run_review


@dataclass(slots=True)
class EvaluationReport:
    cases: list[CaseMetrics] = field(default_factory=list)
    by_category: dict[Category, CaseMetrics] = field(default_factory=dict)
    aggregate_data: dict = field(default_factory=dict)

    def to_markdown(self) -> str:
        return render_report(self)


async def run_evaluation(
    cases: list[EvalCase],
    provider=None,
    policy: ReviewPolicy | None = None,
    run_pipeline: Callable = run_review,
) -> EvaluationReport:
    """Run the review pipeline over a dataset and compute metrics."""
    provider = provider or MockProvider()
    policy = policy or ReviewPolicy.defaults()

    case_metrics: list[CaseMetrics] = []
    per_category: dict[Category, CaseMetrics] = {}

    for case in cases:
        diffs = [parse_patch(f.path, f.patch) for f in case.files]
        sources = case.sources

        async def fetch(path: str, _sources: dict[str, str] = sources) -> str | None:
            return _sources.get(path)

        result = await run_pipeline(diffs, fetch, provider, policy=policy)
        predicted = result.findings
        expected = case.expected

        case_metrics.append(measure(case.id, predicted, expected))
        per_category = _merge_category_metrics(
            per_category, _measure_by_category(case.id, predicted, expected)
        )

    return EvaluationReport(
        cases=case_metrics, by_category=per_category, aggregate_data=aggregate_dict(case_metrics)
    )


def _measure_by_category(
    case_id: str, predicted: list[Finding], expected: list
) -> dict[Category, CaseMetrics]:
    """Measure metrics per category present in the case."""
    cats: set[Category] = set()
    cats.update(f.category for f in predicted)
    cats.update(e.category for e in expected)

    out: dict[Category, CaseMetrics] = {}
    for cat in cats:
        p = [f for f in predicted if f.category == cat]
        e = [x for x in expected if x.category == cat]
        out[cat] = measure(f"{case_id}:{cat.value}", p, e)
    return out


def _merge_category_metrics(
    acc: dict[Category, CaseMetrics], updates: dict[Category, CaseMetrics]
) -> dict[Category, CaseMetrics]:
    from critiq.ai.evaluation.metrics import CaseMetrics as CM

    for cat, m in updates.items():
        if cat not in acc:
            acc[cat] = CM(case_id=f"cat:{cat.value}")
        current = acc[cat]
        current.true_positives += m.true_positives
        current.false_positives += m.false_positives
        current.false_negatives += m.false_negatives
        current.useful += m.useful
    return acc


def aggregate_dict(cases: list[CaseMetrics]) -> dict:
    total_predicted = sum(c.predicted_total for c in cases)
    total_expected = sum(c.expected_total for c in cases)
    tp = sum(c.true_positives for c in cases)
    fp = sum(c.false_positives for c in cases)
    fn = sum(c.false_negatives for c in cases)
    useful = sum(c.useful for c in cases)

    def ratio(num: int, denom: int) -> float:
        return num / denom if denom else 0.0

    return {
        "total_predicted": total_predicted,
        "total_expected": total_expected,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": ratio(tp, total_predicted),
        "recall": ratio(tp, total_expected),
        "false_positive_rate": ratio(fp, total_predicted),
        "useful_rate": ratio(useful, total_predicted),
    }


def render_report(report: EvaluationReport) -> str:
    """Render a markdown evaluation report."""
    a = report.aggregate_data
    lines = [
        "# Critiq Evaluation Report",
        "",
        f"- Predicted findings: **{a['total_predicted']}**",
        f"- Ground-truth findings: **{a['total_expected']}**",
        "",
        "| Metric | Value |",
        "| ------ | ----- |",
        f"| Precision | {a['precision']:.0%} |",
        f"| Recall / Coverage | {a['recall']:.0%} |",
        f"| False-positive rate | {a['false_positive_rate']:.0%} |",
        f"| Useful finding rate | {a['useful_rate']:.0%} |",
        "",
        "## By category",
        "",
        "| Category | Precision | Recall | FP rate |",
        "| -------- | --------- | ------ | ------- |",
    ]
    for cat, m in sorted(report.by_category.items(), key=lambda kv: kv[0].value):
        lines.append(
            f"| {cat.value} | {m.precision:.0%} | {m.recall:.0%} | "
            f"{m.false_positive_rate:.0%} |"
        )
    lines.append("")
    lines.append("## Per case")
    lines.append("")
    for c in report.cases:
        lines.append(
            f"- `{c.case_id}`: P={c.precision:.0%} R={c.recall:.0%} "
            f"FP={c.false_positive_rate:.0%} (TP={c.true_positives}, "
            f"FP={c.false_positives}, FN={c.false_negatives})"
        )
    return "\n".join(lines)
