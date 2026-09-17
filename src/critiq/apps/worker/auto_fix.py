from __future__ import annotations

import logging
from dataclasses import dataclass

from critiq.ai.autofix import PatchEligibility, PatchGenerator, SourceFetcher
from critiq.ai.suggestions import build_suggestion_body, drift_detected
from critiq.analysis.diff import FileDiff
from critiq.apps.worker.test_runner import FAILED, PatchVerifier
from critiq.core.findings import Finding, ReviewComment
from critiq.core.policy import ReviewPolicy

logger = logging.getLogger("critiq.autofix.runner")


@dataclass(slots=True)
class PatchRecord:
    """Metadata for a generated patch, persisted as an AutoFixPatch row."""

    finding: Finding
    file_path: str
    line_start: int
    line_end: int
    version: int
    status: str
    test_status: str
    suggested_replacement: str
    commit_sha: str | None = None
    comment_id: str | None = None
    superseded_by_id: int | None = None


@dataclass(slots=True)
class AutoFixResult:
    comments: list[ReviewComment]
    patches: list[PatchRecord]


class AutoFixRunner:
    """Turns eligible post-gate findings into tested suggestions (AC-2, AC-3).

    Order: generate the patch, degrade to the finding's plain comment when the
    hunk drifted, verify in a workspace, and only replace the finding's review
    comment with a suggestion when its targeted tests passed or could not be
    run. A failed test never posts and never pushes. The suggestion counts
    against `max_comments` because it replaces the finding's existing comment.
    """

    def __init__(
        self,
        policy: ReviewPolicy,
        generator: PatchGenerator | None = None,
        verifier: PatchVerifier | None = None,
    ) -> None:
        self.policy = policy
        self.generator = generator or PatchGenerator(policy=policy)
        self.verifier = verifier or PatchVerifier()

    async def run(
        self,
        diffs: list[FileDiff],
        findings: list[Finding],
        comments: list[ReviewComment],
        fetch: SourceFetcher,
    ) -> AutoFixResult:
        if not self.policy.fix_enabled:
            return AutoFixResult(comments=list(comments), patches=[])

        candidates = PatchEligibility(self.policy).select(diffs, findings)
        if not candidates:
            return AutoFixResult(comments=list(comments), patches=[])

        comments_by_finding = {
            id(c.finding): c for c in comments if c.finding is not None
        }
        updated = list(comments)
        patches: list[PatchRecord] = []

        for candidate in candidates:
            comment = comments_by_finding.get(id(candidate.finding))
            if comment is None:
                continue
            result = await self._suggestion(candidate, comment, fetch)
            if result is None:
                continue
            if result.comment is not None:
                updated[updated.index(comment)] = result.comment
            patches.append(result.patch)

        return AutoFixResult(comments=updated, patches=patches)

    async def _suggestion(
        self, candidate, comment: ReviewComment, fetch: SourceFetcher
    ) -> _SuggestionResult | None:
        path = candidate.file_diff.path
        source = await fetch(path)
        if source is None:
            return None
        patch = await self.generator.generate(candidate, fetch, source=source)
        if patch is None:
            return None
        current = await fetch(path)
        if current is None or drift_detected(source, current, patch.line_start, patch.line_end):
            logger.info(
                "hunk drifted for %s:%d; degrading to plain comment",
                path, patch.line_start,
            )
            return None
        verdict = await self.verifier.verify(
            path, patch.line_start, patch.line_end, patch.replacement_text
        )
        test_status = verdict.status
        if test_status == FAILED:
            logger.info(
                "targeted tests failed for %s:%d; not posting patch",
                path, patch.line_start,
            )
            return _SuggestionResult(
                comment=None,
                patch=PatchRecord(
                    finding=candidate.finding,
                    file_path=path,
                    line_start=patch.line_start,
                    line_end=patch.line_end,
                    version=1,
                    status="failed",
                    test_status="failed",
                    suggested_replacement=patch.replacement_text,
                ),
            )

        return _SuggestionResult(
            comment=ReviewComment(
                file_path=path,
                body=build_suggestion_body(
                    candidate.finding, patch.replacement_text, test_status
                ),
                start_line=patch.line_start,
                end_line=patch.line_end,
                finding=candidate.finding,
            ),
            patch=PatchRecord(
                finding=candidate.finding,
                file_path=path,
                line_start=patch.line_start,
                line_end=patch.line_end,
                version=1,
                status="offered",
                test_status="passed",
                suggested_replacement=patch.replacement_text,
            ),
        )


@dataclass(slots=True)
class _SuggestionResult:
    comment: ReviewComment | None
    patch: PatchRecord
