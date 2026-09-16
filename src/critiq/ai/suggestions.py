from __future__ import annotations

from critiq.core.findings import Finding


def suggestion_block(replacement: str) -> str:
    """GitHub suggestion markdown for a one-click apply replacement."""
    return "```suggestion\n" + replacement.rstrip() + "\n```"


def verdict_tag(status: str) -> str:
    if status == "passed":
        return "_\u2705 Test verified_"
    return "_\u26a0\ufe0f Not test verified_"


def build_suggestion_body(
    finding: Finding, replacement: str, status: str
) -> str:
    """The finding's single review comment: prose + test tag + suggestion."""
    return (
        f"### {finding.severity.value.upper()} \u00b7 {finding.category.value}\n\n"
        f"{finding.title}\n\n"
        f"{finding.explanation}\n\n"
        f"**Evidence:** {finding.evidence}\n\n"
        f"**Recommendation:** {finding.recommendation}\n\n"
        f"Confidence: {finding.confidence:.0%}\n\n"
        f"{verdict_tag(status)}\n\n"
        f"{suggestion_block(replacement)}"
    )


def drift_detected(
    generated_source: str, current_source: str, line_start: int, line_end: int
) -> bool:
    """True when the current head file no longer matches the span the patch
    was generated against, so a suggestion would not apply cleanly (AC-2)."""
    if line_start < 1 or line_end < line_start:
        return True
    before = generated_source.splitlines()
    after = current_source.splitlines()
    if line_end > len(before) or line_end > len(after):
        return True
    return before[line_start - 1 : line_end] != after[line_start - 1 : line_end]
