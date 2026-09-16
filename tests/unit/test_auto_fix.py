
import pytest

from critiq.ai.autofix import GeneratedPatch
from critiq.analysis.diff import parse_patch
from critiq.apps.worker.auto_fix import AutoFixRunner
from critiq.apps.worker.test_runner import FAILED, PASSED, PatchStatus
from critiq.core.findings import Finding, FindingSource, ReviewComment
from critiq.core.policy import Category, ReviewPolicy, Severity

PATCH = """@@ -1,3 +1,4 @@
 def handler():
+    import os
     x = call()
+    os.system(x)
"""
SOURCE = "def handler():\n    import os\n    x = call()\n    os.system(x)\n"


def _finding() -> Finding:
    return Finding(
        category=Category.SECURITY,
        file_path="handler.py",
        title="os.system",
        explanation="Shell command.",
        evidence="`os.system(x)`",
        recommendation="Use subprocess.",
        severity=Severity.HIGH,
        confidence=0.9,
        line_start=4,
        line_end=4,
        source=FindingSource.STATIC,
    )


def _comment(finding: Finding) -> ReviewComment:
    return ReviewComment(
        file_path=finding.file_path,
        body=f"prose: {finding.title}",
        start_line=finding.line_start,
        end_line=finding.line_end,
        finding=finding,
    )


class _FakeGenerator:
    def __init__(self, patch=None):
        self.patch = patch
        self.calls = 0

    async def generate(self, candidate, fetch, source=None):
        self.calls += 1
        return self.patch


class _FakeVerifier:
    def __init__(self, verdict):
        self.verdict = verdict

    async def verify(self, relative_path, start, end, replacement):
        return self.verdict


class _FakeWorkspace:
    def __init__(self, current_source):
        self.current_source = current_source
        self.applied = []

    async def checkout(self):
        return self

    def apply_patch(self, path, start, end, replacement):
        self.applied.append((path, start, end, replacement))


@pytest.mark.asyncio
async def test_passed_replaces_comment_with_suggestion():
    finding = _finding()
    comment = _comment(finding)
    diff = parse_patch("handler.py", PATCH)
    gen_patch = GeneratedPatch(
        finding=finding, file_diff=diff, line_start=4, line_end=4,
        replacement_text="    subprocess.run([x], shell=False)"
    )
    runner = AutoFixRunner(
        policy=ReviewPolicy({"review": {"fix": {"enabled": True}}}),
        generator=_FakeGenerator(patch=gen_patch),
        verifier=_FakeVerifier(PatchStatus(PASSED, "ok")),
    )
    async def fake_fetch(path):
        return SOURCE
    result = await runner.run([diff], [finding], [comment], fake_fetch)
    assert len(result) == 1
    assert result[0] is not comment
    assert "Test verified" in result[0].body
    assert "```suggestion" in result[0].body


@pytest.mark.asyncio
async def test_failed_keeps_original_comment():
    finding = _finding()
    comment = _comment(finding)
    diff = parse_patch("handler.py", PATCH)
    gen_patch = GeneratedPatch(
        finding=finding, file_diff=diff, line_start=4, line_end=4,
        replacement_text="    subprocess.run([x], shell=False)"
    )
    runner = AutoFixRunner(
        policy=ReviewPolicy({"review": {"fix": {"enabled": True}}}),
        generator=_FakeGenerator(patch=gen_patch),
        verifier=_FakeVerifier(PatchStatus(FAILED, "oops")),
    )
    async def fake_fetch(path):
        return SOURCE
    result = await runner.run([diff], [finding], [comment], fake_fetch)
    assert result[0] is comment


@pytest.mark.asyncio
async def test_generator_returns_none_keeps_original_comment():
    finding = _finding()
    comment = _comment(finding)
    diff = parse_patch("handler.py", PATCH)
    runner = AutoFixRunner(
        policy=ReviewPolicy({"review": {"fix": {"enabled": True}}}),
        generator=_FakeGenerator(patch=None),
        verifier=_FakeVerifier(PatchStatus(PASSED)),
    )
    async def fake_fetch(path):
        return SOURCE
    result = await runner.run([diff], [finding], [comment], fake_fetch)
    assert result[0] is comment


@pytest.mark.asyncio
async def test_drift_keeps_original_comment():
    finding = _finding()
    comment = _comment(finding)
    diff = parse_patch("handler.py", PATCH)
    gen_patch = GeneratedPatch(
        finding=finding, file_diff=diff, line_start=4, line_end=4,
        replacement_text="    subprocess.run([x], shell=False)"
    )
    runner = AutoFixRunner(
        policy=ReviewPolicy({"review": {"fix": {"enabled": True}}}),
        generator=_FakeGenerator(patch=gen_patch),
        verifier=_FakeVerifier(PatchStatus(PASSED)),
    )
    drifted_source = SOURCE.replace("os.system(x)", "migrated(x)")
    async def fake_fetch(path):
        return SOURCE if path else SOURCE
    call_count = [0]
    async def drift_fetch(path):
        call_count[0] += 1
        return drifted_source if call_count[0] > 1 else SOURCE
    result = await runner.run([diff], [finding], [comment], drift_fetch)
    assert result[0] is comment


@pytest.mark.asyncio
async def test_disabled_returns_unchanged_comments():
    finding = _finding()
    comment = _comment(finding)
    diff = parse_patch("handler.py", PATCH)
    runner = AutoFixRunner(policy=ReviewPolicy.defaults())
    result = await runner.run([diff], [finding], [comment], lambda p: None)
    assert result == [comment]


@pytest.mark.asyncio
async def test_no_candidates_returns_unchanged_comments():
    finding = Finding(
        category=Category.TESTING,
        file_path="handler.py",
        title="Missing test",
        explanation="e",
        evidence="e",
        recommendation="r",
        severity=Severity.LOW,
        confidence=0.5,
        line_start=1,
        line_end=1,
        source=FindingSource.LLM,
    )
    comment = _comment(finding)
    diff = parse_patch("handler.py", PATCH)
    runner = AutoFixRunner(
        policy=ReviewPolicy({"review": {"fix": {"enabled": True}}}),
    )
    result = await runner.run([diff], [finding], [comment], lambda p: None)
    assert result == [comment]
