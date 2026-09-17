from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from critiq.apps.worker.auto_fix import PatchRecord
from critiq.apps.worker.push import push_patch
from critiq.infrastructure.postgres.models import AutoFixPatch, OrgSetting
from critiq.integrations.github.client import GitHubClient

logger = logging.getLogger("critiq.fix_lifecycle")


def _finding_db_id(
    finding_map: dict[int, int], finding, default: int | None = None
) -> int | None:
    return finding_map.get(id(finding), default)


async def save_patch_rows(
    session: AsyncSession,
    run_id: int,
    finding_map: dict[int, int],
    patches: list[PatchRecord],
    review_comment_id_by_finding: dict[int, int] | None = None,
    commit_sha_by_finding: dict[int, str] | None = None,
) -> list[AutoFixPatch]:
    """Persist AutoFixPatch rows for a completed review (AC-4)."""
    review_comment_id_by_finding = review_comment_id_by_finding or {}
    commit_sha_by_finding = commit_sha_by_finding or {}
    rows: list[AutoFixPatch] = []

    for record in patches:
        finding_db_id = _finding_db_id(finding_map, record.finding)
        if finding_db_id is None:
            logger.warning("patch has no persisted finding id; skipping row")
            continue

        status = record.status
        if id(record.finding) in commit_sha_by_finding:
            status = "applied"

        row = AutoFixPatch(
            review_run_id=run_id,
            finding_id=finding_db_id,
            file_path=record.file_path,
            line_start=record.line_start,
            line_end=record.line_end,
            replacement_text=record.suggested_replacement,
            version=record.version,
            status=status,
            test_status=record.test_status,
            review_comment_id=review_comment_id_by_finding.get(
                id(record.finding)
            ),
            commit_sha=commit_sha_by_finding.get(id(record.finding)),
        )
        session.add(row)
        rows.append(row)

    await session.commit()
    return rows


async def org_push_enabled(session: AsyncSession, repo_name: str) -> bool:
    from critiq.infrastructure.postgres.models import Repository

    repo_row = await session.scalar(
        select(Repository).where(Repository.full_name == repo_name)
    )
    if repo_row is None:
        return False
    setting = await session.scalar(
        select(OrgSetting).where(OrgSetting.repository_id == repo_row.id)
    )
    return bool(setting and setting.auto_push_enabled)


async def push_if_allowed(
    client: GitHubClient,
    repo: str,
    pr: dict,
    patches: list[PatchRecord],
    tested_head_sha: str,
) -> tuple[dict[int, str], list[PatchRecord]]:
    """Push offered patches in push mode (AC-5).

    Returns (commit_sha_by_finding, remaining_patches). Only records whose
    finding persists through a successful compare-and-set push are removed from
    the suggestion set.
    """
    if not patches:
        return {}, []

    commits: dict[int, str] = {}
    remaining: list[PatchRecord] = []
    for record in patches:
        if record.status != "offered":
            remaining.append(record)
            continue
        try:
            sha = await push_patch(
                client,
                repo,
                pr,
                record.file_path,
                record.suggested_replacement,
                tested_head_sha,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "push failed for %s/%s; falling back to suggestion",
                repo,
                record.file_path,
            )
            remaining.append(record)
            continue
        if sha is None:
            remaining.append(record)
            continue
        commits[id(record.finding)] = sha
        logger.info("pushed %s/%s commit %s", repo, record.file_path, sha)

    return commits, remaining
