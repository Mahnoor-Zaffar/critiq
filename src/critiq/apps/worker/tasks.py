from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from arq import create_pool
from sqlalchemy import select

from critiq.apps.worker.fix_lifecycle import (
    org_push_enabled,
    push_if_allowed,
    save_patch_rows,
)
from critiq.apps.worker.reconcile import reconcile_patches
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


@dataclass(slots=True)
class PushState:
    commits: dict[int, str] = field(default_factory=dict)


async def _apply_push_mode(
    client: GitHubClient,
    repo: str,
    number: int,
    session,
    policy: ReviewPolicy,
    result,
) -> PushState:
    """Push offered patches when the double gate passes (AC-5), else leave as-is.

    On a successful push the suggestion comment for that finding is dropped from
    the review and the summary notes the commit.
    """
    if not result.patches or policy.fix_apply != "push":
        return PushState()
    if not await org_push_enabled(session, repo):
        logger.info("push mode skipped for %s: no OrgSetting approval", repo)
        return PushState()

    pr = await client.get_pull_request(repo, number)
    tested_head_sha = pr["head"]["sha"]
    commits, _remaining = await push_if_allowed(
        client, repo, pr, result.patches, tested_head_sha
    )
    if not commits:
        return PushState()

    pushed_finding_ids = set(commits)
    kept_comments = [
        c for c in result.comments if c.finding is None or id(c.finding) not in pushed_finding_ids
    ]
    result.comments = kept_comments
    _note_commits_in_summary(result, commits)
    return PushState(commits=commits)


def _note_commits_in_summary(result, commits: dict[int, str]) -> None:
    shas = ", ".join(f"`{sha[:7]}`" for sha in commits.values())
    result.summary = f"{result.summary}\n\nPushed auto-fix commits: {shas}"


def _map_comment_ids(review_event: dict | None, comments) -> dict[int, int]:
    """Map posted GitHub comment ids back to the finding id behind each comment."""
    if review_event is None:
        return {}
    posted = review_event.get("comments") or []
    mapping: dict[int, int] = {}
    for comment in comments:
        if comment.finding is None:
            continue
        match = next(
            (
                p
                for p in posted
                if p.get("path") == comment.file_path
                and p.get("line") in (comment.end_line, comment.start_line)
            ),
            None,
        )
        if match is not None:
            mapping[id(comment.finding)] = int(match["id"])
    return mapping


async def _reconcile_closed(
    session, client: GitHubClient, repo: str, number: int
) -> None:
    pr = await client.get_pull_request(repo, number)
    await reconcile_patches(
        client, repo, number, pr["head"]["sha"], "closed", session
    )


async def _reconcile_review(
    session, client: GitHubClient, repo: str, number: int
) -> None:
    pr = await client.get_pull_request(repo, number)
    await reconcile_patches(
        client, repo, number, pr["head"]["sha"], "synchronize", session
    )


async def review_pull_request(
    ctx: dict, *, installation_id: int, repo: str, number: int, action: str = "opened"
) -> None:
    """Arq task: run and post a review for a pull request (or save for approval)."""
    auth = GitHubAuth(settings.github_app_id, settings.github_app_private_key)
    token = await auth.get_installation_token(installation_id)
    client = GitHubClient(token)

    policy = await _load_policy(client, repo)
    repo_index = _load_repo_index(repo)

    async with async_session_factory() as session:
        if action == "closed":
            await _reconcile_closed(session, client, repo, number)
            return

        run = await _upsert_run(session, repo, number)
        run.status = "running"
        await session.commit()

        try:
            if action in ("synchronize", "reopened"):
                await _reconcile_review(session, client, repo, number)

            result = await run_review_pipeline(
                client, repo, number, session, policy, repo_index=repo_index
            )
            finding_map = await _save_findings(session, run.id, result)
            patch_state = await _apply_push_mode(
                client, repo, number, session, policy, result
            )

            review_comment_id_by_finding: dict[int, int] = {}
            if policy.mode == "automatic":
                review_event = await post_review(client, repo, number, result)
                review_comment_id_by_finding = _map_comment_ids(
                    review_event, result.comments
                )

            if result.patches:
                await save_patch_rows(
                    session,
                    run.id,
                    finding_map,
                    result.patches,
                    review_comment_id_by_finding=review_comment_id_by_finding,
                    commit_sha_by_finding=patch_state.commits,
                )

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


async def _save_findings(session, run_id: int, result) -> dict[int, int]:
    finding_map: dict[int, int] = {}
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
        await session.flush()
        finding_map[id(f)] = db_f.id
    await session.commit()
    return finding_map


async def get_redis_pool():
    return await create_pool(settings.redis_url)
