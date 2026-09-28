from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from critiq.ai.evaluation.dataset import EvalCase, history_for_case
from critiq.ai.evaluation.metrics import CaseMetrics, measure
from critiq.ai.providers.mock import MockProvider
from critiq.ai.providers.recording import PromptRecord, RecordingProvider
from critiq.analysis.diff import parse_patch
from critiq.core.findings import Finding
from critiq.core.policy import Category, ReviewPolicy
from critiq.pipeline import run_review

RATE_METRICS = ("precision", "recall", "false_positive_rate", "useful_rate")
COUNT_METRICS = (
    "total_predicted",
    "total_expected",
    "true_positives",
    "false_positives",
    "false_negatives",
)


class Arm(StrEnum):
    """Which side of the comparison a run is scoring (AC-4)."""

    NONE = "none"
    CASE = "case"


@dataclass(slots=True)
class EvaluationReport:
    cases: list[CaseMetrics] = field(default_factory=list)
    by_category: dict[Category, CaseMetrics] = field(default_factory=dict)
    aggregate_data: dict = field(default_factory=dict)

    def to_markdown(self) -> str:
        return render_report(self)


@dataclass(slots=True)
class ArmResult:
    """One arm's score beside the prompts that produced it."""

    label: str
    report: EvaluationReport
    prompts: list[PromptRecord] = field(default_factory=list)

    @property
    def prompt_tokens(self) -> int:
        return sum(call.tokens for call in self.prompts)


@dataclass(slots=True)
class ComparisonReport:
    """Both arms and the difference between them (AC-9)."""

    without: ArmResult
    with_history: ArmResult
    deltas: dict[str, float] = field(default_factory=dict)


class ArmRunError(RuntimeError):
    """A pipeline call failed, naming the arm and the case it failed on (AC-11)."""

    def __init__(self, arm: Arm, case_id: str, cause: BaseException) -> None:
        super().__init__(
            f"the {arm.value} arm failed on case {case_id!r}: {type(cause).__name__}: {cause}"
        )
        self.arm = arm
        self.case_id = case_id


async def run_evaluation(
    cases: list[EvalCase],
    provider=None,
    policy: ReviewPolicy | None = None,
    run_pipeline: Callable = run_review,
    arm: Arm = Arm.NONE,
) -> EvaluationReport:
    """Run the review pipeline over a dataset and compute metrics.

    With ``arm`` set to ``case`` each case's recorded history is folded into one
    block and handed to the pipeline. The ``history`` argument is only passed
    then, so a caller injecting its own ``run_pipeline`` that takes no history
    keeps working.
    """
    provider = provider or MockProvider()
    policy = policy or ReviewPolicy.defaults()

    case_metrics: list[CaseMetrics] = []
    per_category: dict[Category, CaseMetrics] = {}

    for case in cases:
        diffs = [parse_patch(f.path, f.patch) for f in case.files]
        sources = case.sources

        async def fetch(path: str, _sources: dict[str, str] = sources) -> str | None:
            return _sources.get(path)

        history = history_for_case(case) if arm is Arm.CASE else None
        if isinstance(provider, RecordingProvider):
            provider.set_authored(_authored_by_file(case))
        try:
            if history is None:
                result = await run_pipeline(diffs, fetch, provider, policy=policy)
            else:
                result = await run_pipeline(diffs, fetch, provider, policy=policy, history=history)
        except Exception as exc:
            raise ArmRunError(arm, case.id, exc) from exc
        predicted = result.findings
        expected = case.expected

        case_metrics.append(measure(case.id, predicted, expected))
        per_category = _merge_category_metrics(
            per_category, _measure_by_category(case.id, predicted, expected)
        )

    return EvaluationReport(
        cases=case_metrics, by_category=per_category, aggregate_data=aggregate_dict(case_metrics)
    )


def _authored_by_file(case: EvalCase) -> Mapping[str, int]:
    return {f.path: f.history_lines_authored for f in case.files}



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


async def compare_arms(
    cases: list[EvalCase],
    provider=None,
    policy: ReviewPolicy | None = None,
    run_pipeline: Callable = run_review,
) -> ComparisonReport:
    """Score the dataset without history and again with it, then the difference.

    Each arm gets its own recorder, so the prompts of one arm are never mixed
    into the other. The two arms run in sequence on the same provider.
    """
    inner = provider or MockProvider()
    results: dict[Arm, ArmResult] = {}
    for arm in (Arm.NONE, Arm.CASE):
        recorder = RecordingProvider(inner)
        report = await run_evaluation(
            cases,
            provider=recorder,
            policy=policy,
            run_pipeline=run_pipeline,
            arm=arm,
        )
        results[arm] = ArmResult(label=arm.value, report=report, prompts=recorder.calls)

    without = results[Arm.NONE]
    with_history = results[Arm.CASE]
    deltas = {
        name: float(with_history.report.aggregate_data[name])
        - float(without.report.aggregate_data[name])
        for name in RATE_METRICS
    }
    deltas["prompt_tokens"] = float(with_history.prompt_tokens - without.prompt_tokens)
    return ComparisonReport(without=without, with_history=with_history, deltas=deltas)


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


RATE_ROWS = (
    ("precision", "Precision"),
    ("recall", "Recall / coverage"),
    ("false_positive_rate", "False positive rate"),
    ("useful_rate", "Useful finding rate"),
)
COUNT_ROWS = (
    ("total_predicted", "Predicted findings"),
    ("total_expected", "Ground truth findings"),
    ("true_positives", "True positives"),
    ("false_positives", "False positives"),
    ("false_negatives", "False negatives"),
)


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _signed_percent(value: float) -> str:
    return f"{value * 100:+.1f}%"


def render_comparison(comparison: ComparisonReport, provider_name: str) -> str:
    """Render both arms, the difference, and what reached each prompt (AC-10).

    Rates carry one decimal place and an explicit sign, because the whole point
    of the comparison is a small difference and the existing single arm report
    rounds to whole percent. The finding counts sit beside every rate so a
    reader can see whether a change came from the numerator or the denominator.
    """
    without = comparison.without.report.aggregate_data
    with_data = comparison.with_history.report.aggregate_data

    lines = ["# Critiq Evaluation Comparison", ""]
    lines.append(_claim_line(provider_name))
    lines.append("")

    lines.append("## Finding quality")
    lines.append("")
    lines.append("| Metric | Without history | With history | Change |")
    lines.append("| ------ | --------------- | ------------ | ------ |")
    for key, label in RATE_ROWS:
        lines.append(
            f"| {label} | {_percent(without[key])} | {_percent(with_data[key])} "
            f"| {_signed_percent(comparison.deltas[key])} |"
        )
    lines.append(
        f"| Prompt tokens | {comparison.without.prompt_tokens} "
        f"| {comparison.with_history.prompt_tokens} "
        f"| {comparison.deltas['prompt_tokens']:+,.0f} |"
    )
    lines.append("")
    lines.extend(_zero_denominator_note(without, with_data))

    lines.append("## Finding counts")
    lines.append("")
    lines.append("| Count | Without history | With history | Change |")
    lines.append("| ----- | --------------- | ------------ | ------ |")
    for key, label in COUNT_ROWS:
        count_change = int(with_data[key]) - int(without[key])
        lines.append(
            f"| {label} | {without[key]} | {with_data[key]} | {count_change:+d} |"
        )
    lines.append("")

    lines.append("## Per case")
    lines.append("")
    lines.append(
        "| Case | Predicted without | Predicted with | Precision without "
        "| Precision with | Change | Recall without | Recall with |"
    )
    lines.append(
        "| ---- | ---------------- | ------------- | ---------------- "
        "| -------------- | ------ | -------------- | ------------ |"
    )
    for without_case, with_case in zip(
        comparison.without.report.cases, comparison.with_history.report.cases, strict=True
    ):
        precision_change = with_case.precision - without_case.precision
        lines.append(
            f"| `{with_case.case_id}` | {without_case.predicted_total} "
            f"| {with_case.predicted_total} "
            f"| {_percent(without_case.precision)} | {_percent(with_case.precision)} "
            f"| {_signed_percent(precision_change)} | {_percent(without_case.recall)} "
            f"| {_percent(with_case.recall)} |"
        )
    lines.append("")

    lines.append("## Prompt observations")
    lines.append("")
    lines.append(f"- Calls recorded: {len(comparison.without.prompts)} without history, "
                 f"{len(comparison.with_history.prompts)} with history")
    lines.append(f"- Prompt tokens: {comparison.without.prompt_tokens} without history, "
                 f"{comparison.with_history.prompt_tokens} with history")
    lines.append("")
    lines.extend(_file_observation_table("Without history", comparison.without))
    lines.extend(_file_observation_table("With history", comparison.with_history))
    lines.append("")
    lines.append(_trim_note(comparison))
    return "\n".join(lines)


def _claim_line(provider_name: str) -> str:
    if provider_name == "mock":
        return (
            f"Provider: **{provider_name}**. This run proves the plumbing only: that a history "
            "block reaches the prompts it belongs on. Its difference is not a quality claim."
        )
    return (
        f"Provider: **{provider_name}**. A real provider run is not repeatable, so a small "
        "difference here is not a result."
    )


def _zero_denominator_note(without: dict, with_data: dict) -> list[str]:
    if without.get("total_predicted") or with_data.get("total_predicted"):
        return []
    return [
        "Both arms predicted nothing, so every rate above reads 0.0% for want of a "
        "denominator rather than because anything was judged wrong."
    ]


def _file_observation_table(title: str, arm: ArmResult) -> list[str]:
    lines = [f"### {title}", ""]
    rows: dict[str, list[PromptRecord]] = {}
    for call in arm.prompts:
        rows.setdefault(call.file or "synthesis (whole review)", []).append(call)
    if not rows:
        return [*lines, "No prompts were recorded.", ""]
    lines.append(
        "| File | Calls | Authored per prompt | Rendered per prompt | Trimmed | Tokens |"
    )
    lines.append("| ---- | ----- | ------------------ | ------------------- | ------- | ------ |")
    for name, calls in rows.items():
        authored = {c.history_lines_authored for c in calls}
        authored_text = (
            "n/a"
            if authored == {None}
            else str(max(c.history_lines_authored or 0 for c in calls))
        )
        rendered = max(c.history_lines_rendered for c in calls)
        lines.append(
            f"| `{name}` | {len(calls)} | {authored_text} | {rendered} "
            f"| {'yes' if _trimmed(calls) else 'no'} "
            f"| {sum(c.tokens for c in calls)} |"
        )
    return [*lines, ""]


def _trimmed(calls: list[PromptRecord]) -> bool:
    return any(_is_trimmed(call) for call in calls)


def _is_trimmed(call: PromptRecord) -> bool:
    return (
        call.history_section
        and call.history_lines_authored is not None
        and call.history_lines_rendered < call.history_lines_authored
    )


def _trim_note(comparison: ComparisonReport) -> str:
    trimmed = [
        call
        for arm in (comparison.without, comparison.with_history)
        for call in arm.prompts
        if _is_trimmed(call)
    ]
    if not trimmed:
        return (
            "No history block was trimmed: every line the cases authored reached each prompt it "
            "belonged on, or the prompt carried no history block at all."
        )
    return (
        f"{len(trimmed)} prompt(s) carried a trimmed history block, so rendered sits below "
        "authored there. A reviewer section is never trimmed; only the synthesizer fits its block "
        "to its budget."
    )
