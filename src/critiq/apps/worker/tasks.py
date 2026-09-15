from __future__ import annotations

import logging
from datetime import UTC, datetime

from arq import create_pool
from sqlalchemy import select

from critiq.apps.worker.review_service import (
    post_review,
)
from critiq.apps.worker.review_service import (
    review_pull_request as run_review_pipeline,
)
from critiq.core.config import settings
from critiq.core.policy import ReviewPolicy
from critiq.core.profiles import build_policy_yaml
from critiq.infrastructure.postgres.models import (
    Finding as DbFinding,
)
from critiq.infrastructure.postgres.models import (
    PullRequest as DbPullRequest,
)
from critiq.infrastructure.postgres.models import (
    Repository as DbRepository,
)
from critiq.infrastructure.postgres.models import (
    ReviewRun as DbReviewRun,
)
from critiq.infrastructure.postgres.session import async_session_factory
from critiq.integrations.github.auth import GitHubAuth
from critiq.integrations.github.client import GitHubClient
from critiq.repository.index import RepoIndex
from critiq.repository.store import IndexCache

logger = logging.getLogger("critiq.worker")


async def review_pull_request(ctx: dict, *, installation_id: int, repo: str, number: int) -> None:
    """Arq task: run and post a review for a pull request (or save for approval)."""
    auth = GitHubAuth(settings.github_app_id, settings.github_app_private_key)
    token = await auth.get_installation_token(installation_id)
    client = GitHubClient(token)

    policy = await _load_policy(client, repo)
    repo_index = _load_repo_index(repo)

    async with async_session_factory() as session:
        run = await _upsert_run(session, repo, number)
        run.status = "running"
        await session.commit()

        try:
            result = await run_review_pipeline(
                client, repo, number, session, policy, repo_index=repo_index
            )
            await _save_findings(session, run.id, result)

            if policy.mode == "automatic":
                await post_review(client, repo, number, result)

            run.status = "success"
            run.decision = result.decision
            run.summary = result.summary
            run.completed_at = datetime.now(UTC)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("review failed for %s#%s", repo, number)
            run.status = "failed"
            run.error = str(exc)
            await session.commit()
            raise


def _load_repo_index(repo: str) -> RepoIndex | None:
    """Load a cached RepoIndex for the repo, or None to fall back to per-PR fetches."""
    try:
        index: RepoIndex | None = IndexCache(settings.repo_index_dir).load(repo)
    except Exception:  # noqa: BLE001
        logger.exception("repo index load failed for %s", repo)
        return None
    if index is None:
        logger.info("no repo index for %s (run `critiq-index` to build one)", repo)
    else:
        logger.info("using repo index for %s (%d files)", repo, index.file_count)
    return index


async def _load_policy(client: GitHubClient, repo: str) -> ReviewPolicy:
    try:
        raw = await client.get_file_content(repo, ".critiq.yml", "HEAD")
    except Exception:  # noqa: BLE001
        raw = None
    return ReviewPolicy(build_policy_yaml(raw))


async def _upsert_run(session, repo: str, number: int) -> DbReviewRun:
    repo_row = await session.scalar(
        select(DbRepository).where(DbRepository.full_name == repo)
    )
    if repo_row is None:
        repo_row = DbRepository(github_repo_id=0, full_name=repo, default_branch="HEAD")
        session.add(repo_row)
        await session.flush()
    pr_row = await session.scalar(
        select(DbPullRequest).where(
            DbPullRequest.repository_id == repo_row.id,
            DbPullRequest.github_pr_number == number,
        )
    )
    if pr_row is None:
        pr_row = DbPullRequest(repository_id=repo_row.id, github_pr_number=number)
        session.add(pr_row)
        await session.flush()
    run = DbReviewRun(pull_request_id=pr_row.id, status="pending")
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def _save_findings(session, run_id: int, result) -> None:
    for f in result.findings:
        db_f = DbFinding(
            review_run_id=run_id,
            category=f.category.value,
            file_path=f.file_path,
            line_start=f.line_start,
            line_end=f.line_end,
            severity=f.severity.value,
            confidence=f.confidence,
            title=f.title,
            explanation=f.explanation,
            evidence=f.evidence,
            recommendation=f.recommendation,
            source=f.source.value,
            posted=True,
        )
        session.add(db_f)
    await session.commit()


async def get_redis_pool():
    return await create_pool(settings.redis_url)
