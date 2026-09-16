from critiq.ai.suggestions import (
    build_suggestion_body,
    drift_detected,
    suggestion_block,
    verdict_tag,
)
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, Severity

FindingObject = object()


def _finding(**kw) -> Finding:
    defaults = dict(
        category=Category.SECURITY,
        file_path="app/handler.py",
        title="Hardcoded secret",
        explanation="A secret is visible.",
        evidence="`KEY = \"x\"` on line 3.",
        recommendation="Use env vars.",
        severity=Severity.HIGH,
        confidence=0.96,
        line_start=3,
        line_end=3,
        source=FindingSource.STATIC,
    )
    defaults.update(kw)
    return Finding(**defaults)


def test_suggestion_block_has_triple_backticks():
    body = suggestion_block("foo = 1\nbar = 2")
    assert body.startswith("```suggestion\n")
    assert body.endswith("\n```")
    assert "foo = 1\nbar = 2" in body


def test_suggestion_block_strips_trailing_whitespace():
    block = suggestion_block("x = 1\n")
    assert block.endswith("\n```")
    assert "x = 1" in block


def test_verdict_tag_verified():
    assert "\u2705 Test verified" in verdict_tag("passed")


def test_verdict_tag_unverified():
    assert "\u26a0\ufe0f Not test verified" in verdict_tag("unverified")


def test_verdict_tag_failed_unverified_fallback():
    assert "Not test verified" in verdict_tag("failed")


def test_build_suggestion_body_contains_expected_sections():
    body = build_suggestion_body(_finding(), "x = 2", "passed")
    assert "HIGH \u00b7 security" in body
    assert "Hardcoded secret" in body
    assert "A secret is visible." in body
    assert "**Evidence:**" in body
    assert "**Recommendation:**" in body
    assert "Confidence: 96%" in body
    assert "Test verified" in body
    assert "```suggestion\nx = 2\n```" in body


def test_drift_detected_returns_false_for_identical_source():
    source = "line1\nline2\nline3\n"
    assert not drift_detected(source, source, 2, 2)


def test_drift_detected_returns_true_when_lines_differ():
    before = "a\nold\nb\n"
    after = "a\nnew\nb\n"
    assert drift_detected(before, after, 2, 2)


def test_drift_detected_returns_true_when_span_out_of_range():
    source = "short\n"
    assert drift_detected(source, source, 5, 5)
