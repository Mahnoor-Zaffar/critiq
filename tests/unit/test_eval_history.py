import asyncio
import sys
from pathlib import Path

import pytest

from critiq.ai.evaluation.cli import build_parser, main
from critiq.ai.evaluation.dataset import (
    EvalCase,
    EvalFile,
    EvalHistory,
    history_for_case,
    load_dataset,
)
from critiq.ai.evaluation.runner import (
    Arm,
    ArmRunError,
    _is_trimmed,
    compare_arms,
    render_comparison,
    run_evaluation,
)
from critiq.ai.history import (
    EMPTY_LINE,
    SYNTHESIS_TOKEN_BUDGET,
    HistoryStatus,
    render_history,
)
from critiq.ai.providers.mock import MockProvider
from critiq.ai.providers.recording import (
    REVIEWER_HISTORY_MARKER,
    SYNTHESIS_HISTORY_MARKER,
    PromptRecord,
    RecordingProvider,
    attributed_file,
    has_history_section,
    rendered_history_lines,
)
from critiq.ai.tokens import estimate_tokens

SAMPLE = Path(__file__).parent.parent.parent / "datasets" / "sample.yml"

AUTHORS = [
    "- Changed in a1b2c3d: add auth helper",
    "- Changed in e4f5a6b: fix token refresh",
    "- Changed in 7c8d9e0: guard against empty session",
    "- Changed in 0f1e2d3: drop the debug log",
]
FINDINGS = ["- Previously flagged in Run 7 (security): hardcoded token"]


def _file(path: str, history: EvalHistory | None = None) -> EvalFile:
    return EvalFile(
        path=path,
        patch=f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,2 @@\n+import os\n+print(os.getcwd())\n",
        source="import os\n",
        history=history,
    )


def _case(*files: EvalFile) -> EvalCase:
    return EvalCase(
        id="case-history",
        repo="example/repo",
        number=1,
        title="t",
        files=list(files),
        expected=[],
    )


def _recording_provider() -> RecordingProvider:
    return RecordingProvider(MockProvider())


def test_a_file_with_no_history_block_is_a_confirmed_empty_record():
    case = _case(_file("app/a.py"))
    block = history_for_case(case)

    assert block.changed_file_count == 1
    entry = block.entry("app/a.py")
    assert entry.status is HistoryStatus.EMPTY
    assert render_history(block, {"app/a.py"}) == f"History Context for app/a.py\n{EMPTY_LINE}"


def test_status_follows_the_lines_unless_the_failure_wording_is_authored():
    assert EvalHistory(commits=AUTHORS).status is HistoryStatus.OK
    assert EvalHistory(findings=FINDINGS).status is HistoryStatus.OK
    assert EvalHistory().status is HistoryStatus.EMPTY
    assert EvalHistory(status_override=HistoryStatus.UNAVAILABLE).status is (
        HistoryStatus.UNAVAILABLE
    )
    assert EvalHistory(status_override=HistoryStatus.NOT_EXPLORED).status is (
        HistoryStatus.NOT_EXPLORED
    )


def test_a_derived_status_cannot_be_authored():
    for rejected in ("ok", "empty", "banana"):
        with pytest.raises(ValueError, match="history status must be one of"):
            EvalHistory.from_dict({"commits": AUTHORS, "status": rejected})


def test_the_fold_has_one_entry_per_changed_file():
    case = _case(
        _file("app/a.py", EvalHistory(commits=tuple(AUTHORS))),
        _file("app/b.py"),
    )
    block = history_for_case(case)

    assert set(block.entries) == {"app/a.py", "app/b.py"}
    assert block.changed_file_count == 2
    assert block.entry("app/a.py").commit_lines == tuple(AUTHORS)
    assert block.entry("app/b.py").status is HistoryStatus.EMPTY


def test_a_dataset_without_history_still_loads_and_keeps_its_files_clean():
    cases = load_dataset(SAMPLE)

    assert all(f.history is None for c in cases for f in c.files)
    assert all(f.history_lines_authored == 0 for c in cases for f in c.files)


async def test_history_reaches_the_prompt_of_the_file_that_authored_it():
    case = _case(
        _file("app/a.py", EvalHistory(commits=tuple(AUTHORS))),
        _file("app/b.py"),
    )
    recorder = _recording_provider()

    await run_evaluation([case], provider=recorder, arm=Arm.CASE)

    for_a = [c for c in recorder.calls if c.file == "app/a.py"]
    for_b = [c for c in recorder.calls if c.file == "app/b.py"]
    assert for_a and for_b

    for call in for_a:
        assert all(line in call.user for line in AUTHORS)
        assert rendered_history_lines(call.user) == len(AUTHORS)
        assert call.history_lines_authored == len(AUTHORS)
        assert call.history_section
    for call in for_b:
        assert not any(line in call.user for line in AUTHORS)
        assert rendered_history_lines(call.user) == 1
        assert EMPTY_LINE in call.user
        assert call.history_lines_authored == 0
        assert call.history_section


async def test_the_without_arm_carries_no_history_section_at_all():
    case = _case(_file("app/a.py", EvalHistory(commits=tuple(AUTHORS))))
    recorder = _recording_provider()

    await run_evaluation([case], provider=recorder, arm=Arm.NONE)

    reviewer_calls = [c for c in recorder.calls if c.file is not None]
    assert reviewer_calls
    for call in reviewer_calls:
        assert REVIEWER_HISTORY_MARKER not in call.user
        assert rendered_history_lines(call.user) == 0
        assert not call.history_section


async def test_the_two_arms_are_never_identical_even_with_nothing_authored():
    case = _case(_file("app/a.py"))

    without = _recording_provider()
    await run_evaluation([case], provider=without, arm=Arm.NONE)
    with_history = _recording_provider()
    await run_evaluation([case], provider=with_history, arm=Arm.CASE)

    without_users = [c.user for c in without.calls]
    with_users = [c.user for c in with_history.calls]
    assert len(without_users) == len(with_users)
    assert without_users != with_users
    assert all(EMPTY_LINE in user for user in with_users if attributed_file(user))


def test_a_synthesis_call_carries_no_file():
    assert attributed_file("Produce the final review.") is None
    assert attributed_file("Changed file: `app/a.py`\n") == "app/a.py"


def test_a_casually_authored_line_still_counts_as_rendered():
    plain = ["renamed the helper"]
    case = _case(_file("app/a.py", EvalHistory(commits=tuple(plain))))
    recorder = _recording_provider()

    asyncio.run(run_evaluation([case], provider=recorder, arm=Arm.CASE))

    call = next(c for c in recorder.calls if c.file == "app/a.py")
    assert call.history_lines_authored == 1
    assert call.history_lines_rendered == 1


def _many_files(count: int = 6, lines: int = 60) -> EvalCase:
    entries = tuple(
        f"- Changed in abc{i:03d}: commit number {i}" for i in range(lines)
    )
    return _case(
        *(_file(f"app/f{i}.py", EvalHistory(commits=entries)) for i in range(count))
    )


def test_a_reviewer_block_never_trims_where_the_synthesis_block_does():
    case = _many_files()
    block = history_for_case(case)
    authored = sum(len(f.history.commits) for f in case.files)

    synthesis = render_history(block)
    reviewer = render_history(block, {"app/f0.py"})
    reviewer_lines = reviewer.splitlines()

    assert synthesis.splitlines()[0] == "Recorded history for 6 of 6 changed files."
    assert len(synthesis.splitlines()) < authored
    assert synthesis.count("History Context for ") == 6
    assert reviewer_lines == ["History Context for app/f0.py", *case.files[0].history.commits]
    assert estimate_tokens(synthesis) <= SYNTHESIS_TOKEN_BUDGET


def test_every_file_keeps_its_header_and_a_floor_of_one_line():
    case = _many_files(count=6, lines=200)
    lines = render_history(history_for_case(case)).splitlines()[1:]

    per_file: dict[str, int] = {}
    for line in lines:
        if line.startswith("History Context for "):
            per_file[line] = 0
        else:
            per_file[next(reversed(per_file))] += 1

    assert len(per_file) == 6
    assert all(count >= 1 for count in per_file.values())


def test_the_recorder_sees_a_trimmed_block_as_trimmed_not_absent():
    case = _many_files()
    block = history_for_case(case)
    prompt = f"{SYNTHESIS_HISTORY_MARKER}\n{render_history(block)}\n\nProduce the final review."
    authored = sum(len(f.history.commits) for f in case.files)

    record = PromptRecord(
        system="",
        user=prompt,
        schema=None,
        file=None,
        tokens=0,
        history_section=has_history_section(prompt),
        history_lines_authored=authored,
        history_lines_rendered=rendered_history_lines(prompt),
    )

    assert record.history_section
    assert record.history_lines_rendered < record.history_lines_authored
    assert _is_trimmed(record)
    assert rendered_history_lines(prompt + "\n- not history: trailing instructions") == (
        record.history_lines_rendered
    )


async def test_the_comparison_scores_both_arms_and_differences_them():
    case = _case(_file("app/a.py", EvalHistory(commits=tuple(AUTHORS))))
    comparison = await compare_arms([case], provider=MockProvider())

    assert comparison.without.label == "none"
    assert comparison.with_history.label == "case"
    assert comparison.without.report.cases[0].case_id == case.id
    assert comparison.with_history.prompt_tokens > comparison.without.prompt_tokens
    assert comparison.deltas["prompt_tokens"] > 0
    assert set(comparison.deltas) == {
        "precision",
        "recall",
        "false_positive_rate",
        "useful_rate",
        "prompt_tokens",
    }


async def test_each_arm_records_into_its_own_recorder():
    case = _case(_file("app/a.py", EvalHistory(commits=tuple(AUTHORS))))
    inner = MockProvider()
    comparison = await compare_arms([case], provider=inner)

    assert comparison.without.prompts
    assert comparison.with_history.prompts
    assert not any(c.history_section for c in comparison.without.prompts)
    assert all(c.history_section for c in comparison.with_history.prompts)


async def test_a_failing_case_names_the_arm_it_failed_in():
    boom = RuntimeError("provider exploded")

    async def broken_pipeline(*_args, **_kwargs):
        raise boom

    with pytest.raises(ArmRunError) as caught:
        await compare_arms([_case(_file("app/a.py"))], run_pipeline=broken_pipeline)

    assert caught.value.arm is Arm.NONE
    assert "none" in str(caught.value)


async def test_a_failing_case_names_the_case_and_keeps_the_cause():
    async def broken_pipeline(*_args, **_kwargs):
        raise RuntimeError("provider exploded")

    with pytest.raises(ArmRunError) as caught:
        await run_evaluation(
            [_case(_file("app/a.py"))],
            provider=MockProvider(),
            arm=Arm.CASE,
            run_pipeline=broken_pipeline,
        )

    assert caught.value.arm is Arm.CASE
    assert caught.value.case_id == "case-history"
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_the_comparison_report_shows_a_rate_change_below_one_percent():
    case = _case(_file("app/a.py", EvalHistory(commits=tuple(AUTHORS))))
    comparison = asyncio.run(compare_arms([case], provider=MockProvider()))
    comparison.deltas["precision"] = 0.004

    text = render_comparison(comparison, "mock")

    assert "+0.4%" in text
    assert "Provider: **mock**" in text
    assert "plumbing only" in text


def test_the_comparison_report_says_a_real_provider_run_is_not_repeatable():
    case = _case(_file("app/a.py", EvalHistory(commits=tuple(AUTHORS))))
    comparison = asyncio.run(compare_arms([case], provider=MockProvider()))

    text = render_comparison(comparison, "openrouter")

    assert "not repeatable" in text
    assert "plumbing only" not in text


def test_the_comparison_report_flags_a_rate_with_no_denominator():
    case = _case(_file("app/a.py"))
    comparison = asyncio.run(compare_arms([case], provider=MockProvider()))

    text = render_comparison(comparison, "mock")

    assert "denominator" in text


def test_the_command_line_compares_both_arms_by_default():
    assert build_parser().parse_args([str(SAMPLE)]).arm == "both"
    assert build_parser().parse_args([str(SAMPLE), "--arm", "none"]).arm == "none"
    assert build_parser().parse_args([str(SAMPLE), "--arm", "case"]).arm == "case"


def test_the_command_line_rejects_an_arm_it_cannot_run(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["critiq-evaluate", str(SAMPLE), "--arm", "sideways"])
    with pytest.raises(SystemExit):
        main()
    assert "--arm" in capsys.readouterr().err


def test_the_command_line_writes_a_comparison_to_a_file(monkeypatch, tmp_path):
    out = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["critiq-evaluate", str(SAMPLE), "--output", str(out)])

    main()

    text = out.read_text(encoding="utf-8")
    assert "Critiq Evaluation Comparison" in text
    assert "| Precision |" in text
    assert "Without history" in text
    assert "With history" in text


def test_the_command_line_can_run_a_single_arm(monkeypatch, tmp_path):
    out = tmp_path / "single.md"
    monkeypatch.setattr(
        sys, "argv", ["critiq-evaluate", str(SAMPLE), "--arm", "none", "--output", str(out)]
    )

    main()

    text = out.read_text(encoding="utf-8")
    assert "Critiq Evaluation Report" in text
    assert "Critiq Evaluation Comparison" not in text
    assert "none arm only" in text
