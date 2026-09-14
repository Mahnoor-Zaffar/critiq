from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from critiq.ai.providers.base import LLMProvider
from critiq.ai.schemas import SYNTHESIS_SCHEMA
from critiq.analysis.diff import FileDiff
from critiq.core.findings import Finding, ReviewComment, ReviewResult
from critiq.core.policy import ReviewPolicy


class EvidenceValidator:
    """Retains only findings backed by real repository evidence."""

    def __init__(self, diffs: list[FileDiff]) -> None:
        self._by_path = {d.path: d for d in diffs}

    def passes(self, finding: Finding) -> bool:
        diff = self._by_path.get(finding.file_path)
        if diff is None:
            return False
        if finding.line_start is not None:
            if not diff.is_line_added(finding.line_start):
                return False
        return True


class Deduper:
    """Merges/removes duplicate findings across reviewers."""

    def dedupe(self, findings: list[Finding]) -> list[Finding]:
        seen: set[tuple] = set()
        kept: list[Finding] = []
        for f in sorted(findings, key=lambda x: -x.confidence):
            key = (f.category, f.file_path, f.line_start, f.title.lower())
            if key in seen:
                continue
            seen.add(key)
            kept.append(f)
        return kept


class Synthesizer:
    def __init__(
        self,
        provider: LLMProvider,
        synthesis_prompt: str,
        policy: ReviewPolicy,
        model: str | None = None,
        max_comments: int | None = None,
        calibrator: Callable[[float, str], float] | None = None,
    ) -> None:
        self.provider = provider
        self.synthesis_prompt = synthesis_prompt
        self.policy = policy
        self.model = model
        self.max_comments = max_comments or policy.max_comments
        self.calibrator = calibrator

    async def synthesize(
        self,
        findings: list[Finding],
        diffs: list[FileDiff],
    ) -> ReviewResult:
        validator = EvidenceValidator(diffs)
        passed = [f for f in findings if validator.passes(f)]
        passed = [f for f in passed if f.passes_policy(self.policy)]
        final = Deduper().dedupe(passed)
        final = self._apply_calibration(final)

        if not final:
            return ReviewResult(
                decision="COMMENT", risk="LOW", summary="No issues found.", findings=[]
            )

        decision, risk, summary = await self._narrative(final)

        comments = self._build_comments(final)
        return ReviewResult(
            decision=decision,
            risk=risk,
            summary=summary,
            comments=comments,
            findings=final,
        )

    async def _narrative(self, findings: list[Finding]) -> tuple[str, str, str]:
        user = (
            "Findings:\n" + "\n".join(_render_finding(f) for f in findings) + "\n\n"
            "Produce the final review."
        )
        try:
            raw = await self.provider.generate(
                system=self.synthesis_prompt,
                user=user,
                schema=SYNTHESIS_SCHEMA,
            )
            decision = raw.get("decision", "COMMENT").upper()
            risk = raw.get("risk", "MEDIUM").upper()
            summary = raw.get("summary", "") or self._fallback_summary(findings)
            return decision, risk, summary
        except Exception:
            return "COMMENT", "MEDIUM", self._fallback_summary(findings)

    def _build_comments(self, findings: list[Finding]) -> list[ReviewComment]:
        comments: list[ReviewComment] = []
        for f in findings[: self.max_comments]:
            body = (
                f"### {f.severity.value.upper()} · {f.category.value}\n\n"
                f"{f.title}\n\n"
                f"{f.explanation}\n\n"
                f"**Evidence:** {f.evidence}\n\n"
                f"**Recommendation:** {f.recommendation}\n\n"
                f"Confidence: {f.confidence:.0%}"
            )
            comments.append(
                ReviewComment(
                    file_path=f.file_path,
                    body=body,
                    start_line=f.line_start,
                    end_line=f.line_end,
                )
            )
        return comments

    def _fallback_summary(self, findings: list[Finding]) -> str:
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
        parts = ", ".join(f"{k}: {v}" for k, v in counts.items()) or "no findings"
        return f"Found {len(findings)} findings ({parts}). See inline comments."

    def _apply_calibration(self, findings: list[Finding]) -> list[Finding]:
        if self.calibrator is None:
            return findings
        return [
            replace(f, confidence=self.calibrator(f.confidence, f.category.value))
            for f in findings
        ]


def _render_finding(f: Finding) -> str:
    return (
        f"- [{f.severity.value.upper()}] {f.category.value} | {f.file_path}"
        f":{f.line_start or '?'} | {f.title} | {f.evidence}"
    )
