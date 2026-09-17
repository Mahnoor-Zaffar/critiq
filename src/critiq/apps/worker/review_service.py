from __future__ import annotations

import logging
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from critiq.ai.history import collect_history
from critiq.ai.providers.base import LLMProvider
from critiq.ai.providers.openrouter import OpenRouterProvider
from critiq.analysis.diff import FileDiff, parse_patch
from critiq.apps.worker.auto_fix import AutoFixRunner
from critiq.apps.worker.feedback_stats import load_feedback_stats
from critiq.apps.worker.test_runner import PatchVerifier
from critiq.apps.worker.workspace import WorkspaceManager
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
    base_sha = pr.get("base", {}).get("sha", "")
    history = await collect_history(client, session, repo, base_sha, diffs)
    result = await run_review(
        diffs,
        fetcher,
        provider,
        policy=policy,
        repo_index=repo_index,
        calibrator=calibrator,
        history=history,
    )

    if policy.fix_enabled and result.findings:
        verifier = _build_verifier(client, repo, pr, number)
        runner = AutoFixRunner(policy=policy, verifier=verifier)
        fix_result = await runner.run(diffs, result.findings, result.comments, fetcher)
        result.comments = fix_result.comments
        result.patches = fix_result.patches

    return result


async def _build_calibrator(session, repo: str):
    """Build a ConfidenceCalibrator from developer feedback, if enabled."""
    if not settings.confidence_calibration or session is None:
        return None
    stats = await load_feedback_stats(session, repo)
    if not stats:
        return None
    return ConfidenceCalibrator(stats)


def _build_verifier(
    client: GitHubClient, repo: str, pr: dict, number: int
) -> PatchVerifier:
    if not settings.admin_token or not settings.workspace_dir:
        return PatchVerifier()
    manager = WorkspaceManager(settings.workspace_dir)
    clone_url = f"https://x-access-token:{client.token}@github.com/{repo}.git"
    base_sha = pr["base"]["sha"]
    head_ref = pr["head"]["sha"]

    async def checkout():
        return await manager.checkout(clone_url, number, head_ref, base_sha)

    return PatchVerifier(workspaces=SimpleNamespace(checkout=checkout))


async def post_review(
    client: GitHubClient,
    repo: str,
    number: int,
    result: ReviewResult,
    event: str = "COMMENT",
) -> dict:
    """Post the review to GitHub (inline comments + body). Returns the response."""
    body = (
        f"## Critiq Review\n\n"
        f"**Decision:** {result.decision}\n"
        f"**Risk:** {result.risk}\n\n"
        f"{result.summary}"
    )
    return await client.create_review(repo, number, body, result.comments, event=event)
