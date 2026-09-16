from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from critiq.ai.providers.base import LLMProvider
from critiq.ai.providers.openrouter import OpenRouterProvider
from critiq.ai.schemas import PATCH_SCHEMA
from critiq.analysis.ast import PythonParser
from critiq.analysis.diff import DiffHunk, FileDiff
from critiq.core.config import settings
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import ReviewPolicy, Severity

logger = logging.getLogger("critiq.autofix")

SourceFetcher = Callable[[str], Awaitable[str | None]]


@dataclass(slots=True, frozen=True)
class PatchCandidate:
    """An AC-1 eligible finding anchored to a single contiguous diff hunk."""

    finding: Finding
    file_diff: FileDiff
    hunk: DiffHunk
    line_start: int
    line_end: int


@dataclass(slots=True)
class GeneratedPatch:
    """A validated replacement for one eligible finding."""

    finding: Finding
    file_diff: FileDiff
    line_start: int
    line_end: int
    replacement_text: str


def _severity_rank(severity: Severity) -> int:
    return {
        Severity.CRITICAL: 4,
        Severity.HIGH: 3,
        Severity.MEDIUM: 2,
        Severity.LOW: 1,
    }[severity]


def _containing_hunk(diff: FileDiff, line_start: int, line_end: int) -> DiffHunk | None:
    for hunk in diff.hunks:
        if hunk.new_start <= line_start and line_end < hunk.new_start + hunk.new_lines:
            return hunk
    return None


def _span_is_added(diff: FileDiff, line_start: int, line_end: int) -> bool:
    hunk = _containing_hunk(diff, line_start, line_end)
    if hunk is None:
        return False
    span = set(range(line_start, line_end + 1))
    return span.issubset(hunk.added_lines)


class PatchEligibility:
    """Selects AC-1 eligible findings, ordered and capped by `max_patches`.

    Runs on post-gate findings (evidence, severity, confidence, dedup). A
    finding is eligible only when its source is a deterministic analyzer, its
    category is in the configured fix categories, its severity and confidence
    pass the review thresholds, and its span is a subset of the PR's added
    lines within a single contiguous hunk of a file the PR modifies.
    """

    def __init__(self, policy: ReviewPolicy) -> None:
        self.policy = policy

    def select(
        self, diffs: list[FileDiff], findings: list[Finding]
    ) -> list[PatchCandidate]:
        if not self.policy.fix_enabled:
            return []
        by_path = {d.path: d for d in diffs}
        candidates: list[PatchCandidate] = []
        for finding in findings:
            candidate = self._candidate(by_path, finding)
            if candidate is not None:
                candidates.append(candidate)
        candidates.sort(
            key=lambda c: (_severity_rank(c.finding.severity), c.finding.confidence),
            reverse=True,
        )
        return candidates[: self.policy.max_patches]

    def _candidate(
        self, by_path: dict[str, FileDiff], finding: Finding
    ) -> PatchCandidate | None:
        if finding.source != FindingSource.STATIC:
            return None
        if finding.category not in self.policy.fix_categories:
            return None
        if not self.policy.passes_confidence(finding.confidence):
            return None
        if _severity_rank(finding.severity) < _severity_rank(
            self.policy.severity_threshold
        ):
            return None
        if finding.line_start is None or finding.line_end is None:
            return None
        if finding.line_start > finding.line_end:
            return None
        diff = by_path.get(finding.file_path)
        if diff is None:
            return None
        hunk = _containing_hunk(diff, finding.line_start, finding.line_end)
        if hunk is None or not _span_is_added(diff, finding.line_start, finding.line_end):
            return None
        return PatchCandidate(
            finding=finding,
            file_diff=diff,
            hunk=hunk,
            line_start=finding.line_start,
            line_end=finding.line_end,
        )


class PatchGenerator:
    """Structured replacement via the strong model, validated and retried.

    The replacement must target the finding's exact span, the resulting buffer
    must still tree-sitter parse cleanly, and generation retries once before a
    logged drop (AC-1).
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        policy: ReviewPolicy | None = None,
        parser: PythonParser | None = None,
    ) -> None:
        self.provider = provider or OpenRouterProvider(model=settings.llm_model_strong)
        self.policy = policy or ReviewPolicy.defaults()
        self.parser = parser or PythonParser()

    async def generate(
        self,
        candidate: PatchCandidate,
        fetch: SourceFetcher,
        source: str | None = None,
    ) -> GeneratedPatch | None:
        if source is None:
            source = await fetch(candidate.file_diff.path)
        if source is None:
            logger.warning("no source for %s; dropping patch", candidate.file_diff.path)
            return None
        for attempt in (1, 2):
            raw = await self._request(source, candidate)
            patch = self._validate(raw, source, candidate)
            if patch is not None:
                return patch
            logger.warning(
                "patch attempt %d invalid for %s:%d-%d",
                attempt,
                candidate.file_diff.path,
                candidate.line_start,
                candidate.line_end,
            )
        logger.warning(
            "dropping patch for %s:%d-%d after 2 attempts",
            candidate.file_diff.path,
            candidate.line_start,
            candidate.line_end,
        )
        return None

    async def _request(
        self, source: str, candidate: PatchCandidate
    ) -> dict[str, Any] | None:
        system = (
            "You write minimal, correct code fixes. Fix only the target lines: "
            "return the new lines to put in place of them. Do not reformat or "
            "rewrite unrelated code."
        )
        user = _build_prompt(source, candidate)
        try:
            raw = await self.provider.generate(
                system=system, user=user, schema=PATCH_SCHEMA
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("patch generation failed: %s", exc)
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def _validate(
        self,
        raw: dict[str, Any] | None,
        source: str,
        candidate: PatchCandidate,
    ) -> GeneratedPatch | None:
        if raw is None:
            return None
        replacement = raw.get("replacement")
        line_start = raw.get("line_start")
        line_end = raw.get("line_end")
        if not isinstance(replacement, str) or not replacement.strip():
            return None
        if (
            not isinstance(line_start, int)
            or not isinstance(line_end, int)
            or (line_start, line_end) != (candidate.line_start, candidate.line_end)
        ):
            return None
        if not _span_is_added(candidate.file_diff, line_start, line_end):
            return None
        patched = _apply(source, line_start, line_end, replacement)
        if not self.parser.validate(patched):
            return None
        return GeneratedPatch(
            finding=candidate.finding,
            file_diff=candidate.file_diff,
            line_start=line_start,
            line_end=line_end,
            replacement_text=replacement,
        )


def _build_prompt(source: str, candidate: PatchCandidate) -> str:
    lines = source.splitlines()
    start, end = candidate.line_start, candidate.line_end
    lo = max(1, start - 5)
    hi = min(len(lines), end + 5)
    context = "\n".join(
        f"{i:4d} | {lines[i - 1]}" for i in range(lo, hi + 1)
    )
    finding = candidate.finding
    span = f'{{"replacement": "<new lines>", "line_start": {start}, "line_end": {end}}}'
    return (
        f"File: {candidate.file_diff.path}\n"
        f"Replace exactly lines {start}-{end} to resolve the finding.\n\n"
        "```python\n" + context + "\n```\n\n"
        f"Finding: {finding.title}\n"
        f"Category: {finding.category.value} | Severity: {finding.severity.value}\n"
        f"Explanation: {finding.explanation}\n"
        f"Evidence: {finding.evidence}\n"
        f"Recommendation: {finding.recommendation}\n\n"
        f"Return a JSON object {span}. The replacement replaces only those lines."
    )


def _apply(source: str, line_start: int, line_end: int, replacement: str) -> str:
    lines = source.splitlines()
    head = lines[: line_start - 1]
    tail = lines[line_end:]
    return "\n".join([*head, replacement, *tail])
