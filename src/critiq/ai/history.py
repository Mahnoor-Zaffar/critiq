from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from critiq.analysis.diff import FileDiff
from critiq.infrastructure.postgres.models import Finding as DbFinding
from critiq.infrastructure.postgres.models import PullRequest as DbPullRequest
from critiq.infrastructure.postgres.models import Repository as DbRepository
from critiq.infrastructure.postgres.models import ReviewRun as DbReviewRun
from critiq.integrations.github.client import GitHubClient

logger = logging.getLogger("critiq.history")

MAX_FILES = 10
COMMITS_PER_FILE = 3
FINDINGS_PER_FILE = 5
TOKEN_BUDGET = 1200
PER_CALL_TIMEOUT = 2.0
AGGREGATE_DEADLINE = 5.0
MAX_CONCURRENCY = 4


async def collect_history(
    client: GitHubClient,
    session: AsyncSession | None,
    repo: str,
    base_sha: str,
    diffs: list[FileDiff],
    *,
    per_call_timeout: float = PER_CALL_TIMEOUT,
    aggregate_deadline: float = AGGREGATE_DEADLINE,
) -> str:
    """Best-effort history block for the changed files (AC-7, AC-8).

    Never raises: any failure, timeout, or empty record set yields an empty
    string and the review proceeds with zero history.
    """
    try:
        groups = await _collect(
            client,
            session,
            repo,
            base_sha,
            diffs,
            per_call_timeout=per_call_timeout,
            aggregate_deadline=aggregate_deadline,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("history collection failed: %s", exc)
        return ""
    return _aggregate(groups)


async def _collect(
    client: GitHubClient,
    session: AsyncSession | None,
    repo: str,
    base_sha: str,
    diffs: list[FileDiff],
    *,
    per_call_timeout: float,
    aggregate_deadline: float,
) -> list[list[str]]:
    paths = [fd.path for fd in diffs[:MAX_FILES]]
    if not paths:
        return []
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def one(path: str) -> list[str]:
        async with semaphore:
            commits = await _recent_commits(
                client, repo, base_sha, path, per_call_timeout
            )
            if commits is None:
                return []
            findings = await _prior_findings(session, repo, path)
            lines = [
                f"- Changed in {commit['sha'][:7]}: {commit['message']}"
                for commit in commits
            ]
            lines.extend(
                f"- Previously flagged in Run {run_id} ({category}): {title}"
                for run_id, category, title in findings
            )
            if not lines:
                return []
            return [path, *lines]

    tasks = [asyncio.create_task(one(path)) for path in paths]
    done, pending = await asyncio.wait(tasks, timeout=aggregate_deadline)
    for task in pending:
        task.cancel()

    groups: list[list[str]] = []
    for task in done:
        if task.cancelled():
            continue
        try:
            lines = await task
        except Exception as exc:  # noqa: BLE001
            logger.debug("history skipped for a changed file: %s", exc)
            continue
        if lines:
            groups.append(lines)
    return groups


async def _recent_commits(
    client: GitHubClient,
    repo: str,
    base_sha: str,
    path: str,
    timeout: float,
) -> list[dict] | None:
    """Commits for one file, or None when the API call failed (AC-8)."""
    if not base_sha:
        return []
    try:
        return await asyncio.wait_for(
            client.get_recent_commits(repo, base_sha, path, per_page=COMMITS_PER_FILE),
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("commits query failed for %s: %s", path, exc)
        return None


async def _prior_findings(
    session: AsyncSession | None, repo: str, path: str
) -> list[tuple[int, str, str]]:
    """Up to FINDINGS_PER_FILE prior (completed) findings on ``path`` in ``repo``."""
    if session is None:
        return []
    stmt = (
        select(DbFinding.file_path, DbFinding.title, DbFinding.category, DbReviewRun.id)
        .join(DbReviewRun, DbFinding.review_run_id == DbReviewRun.id)
        .join(DbPullRequest, DbReviewRun.pull_request_id == DbPullRequest.id)
        .join(DbRepository, DbPullRequest.repository_id == DbRepository.id)
        .where(DbRepository.full_name == repo)
        .where(DbFinding.file_path == path)
        .where(DbReviewRun.completed_at.is_not(None))
        .order_by(DbReviewRun.completed_at.desc())
        .limit(FINDINGS_PER_FILE)
    )
    try:
        rows = (await session.execute(stmt)).all()
    except Exception as exc:  # noqa: BLE001
        logger.debug("prior findings query failed for %s: %s", path, exc)
        return []
    return [(row[3], row[2], row[1]) for row in rows]


def _aggregate(groups: list[list[str]]) -> str:
    groups.sort(key=lambda group: group[0])
    lines = [line for group in groups for line in group]
    return "\n".join(_fit_budget(lines))


def _fit_budget(lines: list[str], budget: int = TOKEN_BUDGET) -> list[str]:
    """Trim the longest entries first until the whole block fits the token budget."""
    if _token_cost(lines) <= budget:
        return lines
    work = list(lines)
    while work and _token_cost(work) > budget:
        work.remove(max(work, key=len))
    return work


def _token_cost(lines: list[str]) -> int:
    return len("\n".join(lines)) // 4
