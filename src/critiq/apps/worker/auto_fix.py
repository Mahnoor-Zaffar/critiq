from __future__ import annotations

import logging

from critiq.ai.autofix import PatchEligibility, PatchGenerator, SourceFetcher
from critiq.ai.suggestions import build_suggestion_body, drift_detected
from critiq.analysis.diff import FileDiff
from critiq.apps.worker.test_runner import FAILED, PatchVerifier
from critiq.core.findings import Finding, ReviewComment
from critiq.core.policy import ReviewPolicy

logger = logging.getLogger("critiq.autofix.runner")


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
    ) -> list[ReviewComment]:
        if not self.policy.fix_enabled:
            return comments
        candidates = PatchEligibility(self.policy).select(diffs, findings)
        if not candidates:
            return comments
        comments_by_finding = {
            id(c.finding): c for c in comments if c.finding is not None
        }
        updated = list(comments)
        for candidate in candidates:
            comment = comments_by_finding.get(id(candidate.finding))
            if comment is None:
                continue
            replacement = await self._suggestion(candidate, comment, fetch)
            if replacement is not None:
                updated[updated.index(comment)] = replacement
        return updated

    async def _suggestion(
        self, candidate, comment: ReviewComment, fetch: SourceFetcher
    ) -> ReviewComment | None:
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
        if verdict.status == FAILED:
            logger.info(
                "targeted tests failed for %s:%d; not posting patch",
                path, patch.line_start,
            )
            return None
        return ReviewComment(
            file_path=path,
            body=build_suggestion_body(
                candidate.finding, patch.replacement_text, verdict.status
            ),
            start_line=patch.line_start,
            end_line=patch.line_end,
            finding=candidate.finding,
        )
