from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from critiq.ai.providers.base import LLMProvider
from critiq.ai.providers.openrouter import OpenRouterProvider
from critiq.analysis.diff import FileDiff, parse_patch
from critiq.apps.worker.feedback_stats import load_feedback_stats
from critiq.core.config import settings
from critiq.core.feedback import ConfidenceCalibrator
from critiq.core.findings import ReviewResult
from critiq.core.policy import ReviewPolicy
from critiq.integrations.github.client import GitHubClient
from critiq.pipeline import run_review

logger = logging.getLogger("critiq.review")


def build_github_fetcher(client: GitHubClient, repo: str, ref: str):
    async def fetch(path: str) -> str | None:
        try:
            return await client.get_file_content(repo, path, ref)
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch %s failed: %s", path, exc)
            return None

    return fetch


async def review_pull_request(
    client: GitHubClient,
    repo: str,
    number: int,
    session: AsyncSession,
    policy: ReviewPolicy | None = None,
    provider: LLMProvider | None = None,
    repo_index=None,
) -> ReviewResult:
    """Fetch a PR, run the pipeline, and return the result (not yet posted)."""
    pr = await client.get_pull_request(repo, number)
    head_ref = pr["head"]["sha"]
    files = await client.get_pull_files(repo, number)

    diffs: list[FileDiff] = [parse_patch(f.filename, f.patch) for f in files]
    fetcher = build_github_fetcher(client, repo, head_ref)

    policy = policy or ReviewPolicy.defaults()
    provider = provider or OpenRouterProvider(model=settings.llm_model_cheap)
    calibrator = await _build_calibrator(session, repo)
    result = await run_review(
        diffs,
        fetcher,
        provider,
        policy=policy,
        repo_index=repo_index,
        calibrator=calibrator,
    )

    return result


async def _build_calibrator(session, repo: str):
    """Build a ConfidenceCalibrator from developer feedback, if enabled."""
    if not settings.confidence_calibration or session is None:
        return None
    stats = await load_feedback_stats(session, repo)
    if not stats:
        return None
    return ConfidenceCalibrator(stats)


async def post_review(
    client: GitHubClient,
    repo: str,
    number: int,
    result: ReviewResult,
    event: str = "COMMENT",
) -> None:
    """Post the review to GitHub (inline comments + body)."""
    body = (
        f"## Critiq Review\n\n"
        f"**Decision:** {result.decision}\n"
        f"**Risk:** {result.risk}\n\n"
        f"{result.summary}"
    )
    await client.create_review(repo, number, body, result.comments, event=event)
