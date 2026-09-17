from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import select

from critiq.infrastructure.postgres.models import AutoFixPatch, ReviewRun
from critiq.integrations.github.client import GitHubClient

logger = logging.getLogger("critiq.reconcile")

Action = Literal["synchronize", "reopened", "closed"]


async def reconcile_patches(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    head_sha: str,
    action: Action,
    session,
) -> list[dict]:
    """Reconcile offered patches on sync/reopen/close events (AC-4).

    Returns descriptors of rows regenerated so the caller can re-persist comment
    ids or trigger full regeneration.
    """
    run = await _latest_run(session, repo, pr_number)
    if run is None:
        return []

    rows = (
        await session.scalars(
            select(AutoFixPatch).where(
                AutoFixPatch.review_run_id == run.id,
                AutoFixPatch.status == "offered",
            )
        )
    ).all()

    if not rows:
        return []

    if action == "closed":
        await _mark_all_rejected(session, rows)
        return []

    regenerated: list[dict] = []
    for row in rows:
        outcome = await _reconcile_one(client, repo, pr_number, head_sha, row)
        if outcome == "regenerate":
            regenerated.append(
                {
                    "id": row.id,
                    "file_path": row.file_path,
                    "line_start": row.line_start,
                    "line_end": row.line_end,
                    "version": row.version,
                    "finding_id": row.finding_id,
                }
            )
        elif outcome == "applied":
            logger.info(
                "patch %s/%s marked applied on %s", row.file_path, row.id, action
            )
        elif outcome == "rejected":
            logger.info(
                "patch %s/%s marked rejected (basis gone)", row.file_path, row.id
            )
    await session.commit()
    return regenerated


async def _latest_run(session, repo: str, pr_number: int) -> ReviewRun | None:
    from critiq.infrastructure.postgres.models import PullRequest

    return await session.scalar(
        select(ReviewRun)
        .join(ReviewRun.pull_request)
        .where(
            PullRequest.github_pr_number == pr_number,
            PullRequest.repository.has(full_name=repo),
        )
        .order_by(ReviewRun.id.desc())
        .limit(1)
    )


async def _reconcile_one(
    client: GitHubClient,
    repo: str,
    pr_number: int,
    head_sha: str,
    row: AutoFixPatch,
) -> str | None:
    """Run the three-check decision tree on a single offered patch row."""
    head_source = await client.get_file_content(repo, row.file_path, head_sha)
    if head_source is None:
        logger.warning("cannot fetch %s at %s; skipping reconcile", row.file_path, head_sha)
        return None

    if row.replacement_text in head_source:
        row.status = "applied"
        return "applied"

    basis_in_diff = await client.patch_diff_basis(
        repo, pr_number, row.file_path, row.line_start or 0
    )
    if not basis_in_diff:
        row.status = "rejected"
        return "rejected"

    new_version = row.version + 1
    row.version = new_version
    row.test_status = "unverified"
    if row.review_comment_id is not None:
        await _note_supersession(client, repo, row.review_comment_id, new_version, row.file_path)
    return "regenerate"


async def _note_supersession(
    client: GitHubClient,
    repo: str,
    comment_id: int,
    new_version: int,
    file_path: str,
) -> None:
    note = (
        f"\n\n> **Superseded by v{new_version}** — the hunk moved and this "
        f"patch was regenerated in a newer review of `{file_path}`."
    )
    try:
        current = await client.get_review_comment(repo, comment_id)
    except Exception:  # noqa: BLE001
        logger.warning("cannot read comment %s for supersession note", comment_id)
        return
    await client.update_review_comment(repo, comment_id, f"{current}{note}")


async def _mark_all_rejected(session, rows) -> None:
    for row in rows:
        row.status = "rejected"
    await session.commit()
