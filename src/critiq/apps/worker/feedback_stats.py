from __future__ import annotations

import logging

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from critiq.core.feedback import FeedbackStats
from critiq.infrastructure.postgres.models import (
    Finding as DbFinding,
)
from critiq.infrastructure.postgres.models import (
    FindingFeedback as DbFeedback,
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

logger = logging.getLogger("critiq.worker")


async def load_feedback_stats(session: AsyncSession, repo: str) -> dict[str, FeedbackStats]:
    """Per-category feedback stats for *repo*, falling back to global stats.

    Uses repo-local signals when the repo has any history; otherwise falls back
    to all repositories' signals so a new repo can still benefit from what the
    team has learned elsewhere while building its own track record.
    """
    stats = await _category_stats(session, repo=repo)
    if not stats:
        stats = await _category_stats(session, repo=None)
    if stats:
        logger.debug("loaded %d category feedback stats for %s", len(stats), repo)
    return stats


async def _category_stats(
    session: AsyncSession, repo: str | None
) -> dict[str, FeedbackStats]:
    accepted = _signal_count("accepted")
    resolved = _signal_count("resolved")
    stmt = (
        select(DbFinding.category, func.count(), accepted, resolved)
        .join(DbFeedback, DbFeedback.finding_id == DbFinding.id)
        .group_by(DbFinding.category)
    )
    if repo is not None:
        stmt = (
            stmt.join(DbReviewRun, DbFinding.review_run_id == DbReviewRun.id)
            .join(DbPullRequest, DbReviewRun.pull_request_id == DbPullRequest.id)
            .join(DbRepository, DbPullRequest.repository_id == DbRepository.id)
            .where(DbRepository.full_name == repo)
        )
    rows = (await session.execute(stmt)).all()
    return {
        category: FeedbackStats(
            category=category,
            total=int(total),
            accepted=int(accepted),
            resolved=int(resolved),
        )
        for category, total, accepted, resolved in rows
        if total
    }


def _signal_count(signal: str):
    return func.sum(case((DbFeedback.signal == signal, 1), else_=0))
