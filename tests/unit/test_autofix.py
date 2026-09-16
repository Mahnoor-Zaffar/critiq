import asyncio

import pytest

from critiq.ai.autofix import PatchEligibility, PatchGenerator
from critiq.analysis.diff import parse_patch
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, ReviewPolicy, Severity

PATCH = """@@ -1,4 +1,5 @@
 def handler():
+    import os
     x = call()
+    os.system(x)
     return
"""

SOURCE = """def handler():
    import os
    x = "echo hi"
    os.system(x)
    return
"""


def _finding(
    *,
    file_path="app/handler.py",
    line_start=4,
    line_end=4,
    category=Category.SECURITY,
    severity=Severity.HIGH,
    confidence=0.9,
    source=FindingSource.STATIC,
    title="os.system command invocation",
) -> Finding:
    return Finding(
        category=category,
        file_path=file_path,
        title=title,
        explanation="os.system runs a shell command.",
        evidence="`os.system(x)` on line 4.",
        recommendation="Use subprocess.run.",
        severity=severity,
        confidence=confidence,
        line_start=line_start,
        line_end=line_end,
        source=source,
    )


def _policy(**fix) -> ReviewPolicy:
    data = {"review": {"fix": fix}} if fix else {}
    return ReviewPolicy(data)


class _FakeProvider:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def generate(self, *, system, user, schema):
        self.calls += 1
        return self.responses.pop(0)


async def _fetch(path):
    return SOURCE


def test_eligible_static_finding_is_selected():
    diff = parse_patch("app/handler.py", PATCH)
    policy = _policy(enabled=True)
    selected = PatchEligibility(policy).select([diff], [_finding()])
    assert len(selected) == 1
    assert selected[0].line_start == 4
    assert selected[0].line_end == 4


@pytest.mark.parametrize(
    "mutate",
    [
        {"source": FindingSource.LLM},
        {"category": Category.TESTING},
        {"severity": Severity.LOW},
        {"confidence": 0.5},
        {"line_start": 3, "line_end": 3},
    ],
)
def test_ineligible_sources_are_not_selected(mutate):
    diff = parse_patch("app/handler.py", PATCH)
    finding = _finding(**mutate)
    assert PatchEligibility(_policy(enabled=True)).select([diff], [finding]) == []


def test_file_not_in_diff_is_not_selected():
    diff = parse_patch("app/handler.py", PATCH)
    finding = _finding(file_path="app/other.py")
    assert PatchEligibility(_policy(enabled=True)).select([diff], [finding]) == []


def test_span_crossing_hunks_is_not_selected():
    patch = """@@ -1,2 +1,2 @@
 def handler():
+    import os
@@ -6,2 +6,2 @@
 def other():
-    pass
+    return 1
"""
    diff = parse_patch("app/handler.py", patch)
    finding = _finding(line_start=2, line_end=7)
    assert PatchEligibility(_policy(enabled=True)).select([diff], [finding]) == []


def test_disabled_fix_block_selects_nothing():
    diff = parse_patch("app/handler.py", PATCH)
    selected = PatchEligibility(ReviewPolicy.defaults()).select([diff], [_finding()])
    assert selected == []


def test_max_patches_orders_severity_then_confidence_then_keeps_creation_order():
    diff = parse_patch("app/handler.py", PATCH)
    findings = [
        _finding(severity=Severity.HIGH, confidence=0.95, title="A"),
        _finding(severity=Severity.HIGH, confidence=0.88, title="B"),
        _finding(severity=Severity.MEDIUM, confidence=0.99, title="C"),
        _finding(severity=Severity.CRITICAL, confidence=0.9, title="D"),
    ]
    policy = _policy(enabled=True, max_patches=2)
    selected = PatchEligibility(policy).select([diff], findings)
    assert [c.finding.title for c in selected] == ["D", "A"]


def test_generator_returns_validated_patch():
    provider = _FakeProvider(
        {"replacement": "    subprocess.run([x], shell=False)", "line_start": 4, "line_end": 4}
    )
    diff = parse_patch("app/handler.py", PATCH)
    candidate = PatchEligibility(_policy(enabled=True)).select([diff], [_finding()])[0]
    generator = PatchGenerator(provider=provider, policy=_policy(enabled=True))

    patch = asyncio.run(generator.generate(candidate, _fetch))

    assert patch is not None
    assert patch.replacement_text == "    subprocess.run([x], shell=False)"
    assert patch.line_start == 4
    assert patch.line_end == 4
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_generator_retries_once_then_succeeds():
    provider = _FakeProvider(
        {"replacement": "    nope", "line_start": 3, "line_end": 3},
        {"replacement": "    subprocess.run([x], shell=False)", "line_start": 4, "line_end": 4},
    )
    diff = parse_patch("app/handler.py", PATCH)
    candidate = PatchEligibility(_policy(enabled=True)).select([diff], [_finding()])[0]
    generator = PatchGenerator(provider=provider, policy=_policy(enabled=True))

    patch = await generator.generate(candidate, _fetch)

    assert patch is not None
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_generator_drops_after_two_bad_attempts():
    provider = _FakeProvider(
        {"replacement": "    nope", "line_start": 3, "line_end": 3},
        {"replacement": "    nope", "line_start": 5, "line_end": 5},
    )
    diff = parse_patch("app/handler.py", PATCH)
    candidate = PatchEligibility(_policy(enabled=True)).select([diff], [_finding()])[0]
    generator = PatchGenerator(provider=provider, policy=_policy(enabled=True))

    patch = await generator.generate(candidate, _fetch)

    assert patch is None
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_generator_drops_syntax_breaking_replacement():
    provider = _FakeProvider(
        {"replacement": "    def (: oops", "line_start": 4, "line_end": 4},
        {"replacement": "    def (: oops", "line_start": 4, "line_end": 4},
    )
    diff = parse_patch("app/handler.py", PATCH)
    candidate = PatchEligibility(_policy(enabled=True)).select([diff], [_finding()])[0]
    generator = PatchGenerator(provider=provider, policy=_policy(enabled=True))

    patch = await generator.generate(candidate, _fetch)

    assert patch is None
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_generator_skips_when_source_unavailable():
    provider = _FakeProvider()
    diff = parse_patch("app/handler.py", PATCH)
    candidate = PatchEligibility(_policy(enabled=True)).select([diff], [_finding()])[0]
    generator = PatchGenerator(provider=provider, policy=_policy(enabled=True))

    async def no_source(path):
        return None

    patch = await generator.generate(candidate, no_source)

    assert patch is None
    assert provider.calls == 0
