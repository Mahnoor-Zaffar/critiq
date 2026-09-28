from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from critiq.ai.tokens import estimate_tokens
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
MAX_VALUE_CHARS = 120
REVIEWER_TOKEN_BUDGET = 400
SYNTHESIS_TOKEN_BUDGET = 1200
PER_CALL_TIMEOUT = 2.0
AGGREGATE_DEADLINE = 5.0
DB_QUERY_TIMEOUT = 1.0
MAX_CONCURRENCY = 4

EMPTY_LINE = "- No recorded history for this file before this pull request."
UNAVAILABLE_LINE = "- History for this file is unavailable in this review."


class HistoryStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    NOT_EXPLORED = "not_explored"


@dataclass(frozen=True, slots=True)
class PathHistory:
    """What was learned about one file, and how sure we are of it (AC-9)."""

    path: str
    status: HistoryStatus
    commit_lines: tuple[str, ...] = ()
    finding_lines: tuple[str, ...] = ()

    @property
    def detail_lines(self) -> tuple[str, ...]:
        return self.commit_lines + self.finding_lines


@dataclass(frozen=True, slots=True)
class HistoryBlock:
    """The raw collected block, one entry per changed file, keyed by path.

    The only carrier of history between collection and the two renders, so no
    consumer can read a pre-rendered view another consumer cannot see.
    """

    entries: Mapping[str, PathHistory] = field(default_factory=dict)
    changed_file_count: int = 0

    @property
    def explored_paths(self) -> list[str]:
        return sorted(
            path
            for path, entry in self.entries.items()
            if entry.status is not HistoryStatus.NOT_EXPLORED
        )

    def entry(self, path: str) -> PathHistory:
        return self.entries.get(path) or PathHistory(path, HistoryStatus.NOT_EXPLORED)


async def collect_history(
    client: GitHubClient,
    session: AsyncSession | None,
    repo: str,
    base_sha: str,
    diffs: list[FileDiff],
    *,
    per_call_timeout: float = PER_CALL_TIMEOUT,
    aggregate_deadline: float = AGGREGATE_DEADLINE,
    db_timeout: float = DB_QUERY_TIMEOUT,
) -> HistoryBlock:
    """Best-effort history for the changed files (AC-7, AC-8, AC-9, AC-10).

    Never raises: a failure or timeout leaves that file ``unavailable`` and the
    review proceeds. Absence of history is only ever claimed for a file whose
    lookups actually succeeded and came back empty.
    """
    if not diffs:
        return HistoryBlock()

    # The files that cost the most prompt tokens are the files worth exploring.
    ranked = sorted(diffs, key=lambda fd: (-len(fd.added_lines), fd.path))
    entries: dict[str, PathHistory] = {
        fd.path: PathHistory(fd.path, HistoryStatus.NOT_EXPLORED) for fd in diffs
    }
    try:
        collected = await _collect(
            client,
            session,
            repo,
            base_sha,
            ranked[:MAX_FILES],
            per_call_timeout=per_call_timeout,
            aggregate_deadline=aggregate_deadline,
            db_timeout=db_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("history collection failed: %s", exc)
        return HistoryBlock(entries=entries, changed_file_count=len(diffs))
    entries.update({entry.path: entry for entry in collected})
    return HistoryBlock(entries=entries, changed_file_count=len(diffs))


async def _collect(
    client: GitHubClient,
    session: AsyncSession | None,
    repo: str,
    base_sha: str,
    explored: list[FileDiff],
    *,
    per_call_timeout: float,
    aggregate_deadline: float,
    db_timeout: float,
) -> list[PathHistory]:
    if not base_sha:
        # A missing input is not evidence of an empty history.
        return [PathHistory(fd.path, HistoryStatus.UNAVAILABLE) for fd in explored]

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def commits_for(fd: FileDiff) -> list[dict] | None:
        async with semaphore:
            return await _recent_commits(client, repo, base_sha, fd.path, per_call_timeout)

    tasks = [asyncio.create_task(commits_for(fd)) for fd in explored]
    done, pending = await asyncio.wait(tasks, timeout=aggregate_deadline)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    commits_by_path: dict[str, list[dict] | None] = {}
    for fd, task in zip(explored, tasks, strict=True):
        if task not in done:
            continue
        try:
            commits_by_path[fd.path] = task.result()
        except Exception as exc:  # noqa: BLE001
            logger.debug("commits lookup failed for %s: %s", fd.path, exc)

    # An AsyncSession wraps a single connection and refuses concurrent use, so the
    # database leg runs serially, one indexed query per file, after the HTTP leg.
    entries: list[PathHistory] = []
    for fd in explored:
        if fd.path not in commits_by_path:
            entries.append(PathHistory(fd.path, HistoryStatus.UNAVAILABLE))
            continue
        commits = commits_by_path[fd.path]
        findings = await _prior_findings(session, repo, fd.path, db_timeout)
        commit_lines = tuple(
            f"- Changed in {commit['sha'][:7]}: {_truncate(commit['message'])}"
            for commit in (commits or ())[:COMMITS_PER_FILE]
        )
        finding_lines = tuple(
            f"- Previously flagged in Run {run_id} ({category}): {_truncate(title)}"
            for run_id, category, title in (findings or ())[:FINDINGS_PER_FILE]
        )
        if commit_lines or finding_lines:
            status = HistoryStatus.OK
        elif commits is not None and findings is not None:
            status = HistoryStatus.EMPTY
        else:
            status = HistoryStatus.UNAVAILABLE
        entries.append(
            PathHistory(fd.path, status, commit_lines, finding_lines)
        )
    return entries


async def _recent_commits(
    client: GitHubClient,
    repo: str,
    base_sha: str,
    path: str,
    timeout: float,
) -> list[dict] | None:
    """Commits for one file, or None when the API call failed (AC-8)."""
    try:
        return await asyncio.wait_for(
            client.get_recent_commits(repo, base_sha, path, per_page=COMMITS_PER_FILE),
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("commits query failed for %s: %s", path, exc)
        return None


async def _prior_findings(
    session: AsyncSession | None, repo: str, path: str, timeout: float
) -> list[tuple[int, str, str]] | None:
    """Up to FINDINGS_PER_FILE prior findings, or None when the lookup failed."""
    if session is None:
        return None
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
        result = await asyncio.wait_for(session.execute(stmt), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prior findings query failed for %s: %s", path, exc)
        return None
    return [(row[3], row[2], row[1]) for row in result.all()]


def render_history(
    block: HistoryBlock | None,
    paths: Collection[str] | None = None,
    *,
    budget: int = SYNTHESIS_TOKEN_BUDGET,
) -> str:
    """The single route into a prompt (AC-9).

    ``paths`` selects the slice: one file for a reviewer, which renders only the
    history of the file it is judging, or ``None`` for the synthesizer, which
    renders every explored file. Both renders read the raw block at call time.
    """
    if block is None:
        return ""
    if paths is not None:
        lines = [line for path in sorted(paths) for line in _section_lines(block.entry(path))]
        return "\n".join(lines)
    return _render_all(block, budget=budget)


def _render_all(block: HistoryBlock, *, budget: int) -> str:
    entries = [block.entries[path] for path in block.explored_paths]
    if not entries:
        return ""
    # Reserve the count line up front, then report what actually survived so a
    # trimmed block is visible rather than silently partial.
    kept = _fit(entries, budget - estimate_tokens(_count_line(len(entries), block)))
    lines = [_count_line(len(kept), block)]
    for entry in kept:
        lines.extend(_section_lines(entry))
    return "\n".join(lines)


def _count_line(kept: int, block: HistoryBlock) -> str:
    return (
        f"Recorded history for {kept} of {block.changed_file_count} changed files."
    )


def _section_lines(entry: PathHistory) -> list[str]:
    header = f"History Context for {entry.path}"
    if entry.status is HistoryStatus.OK:
        return [header, *entry.detail_lines]
    absence = EMPTY_LINE if entry.status is HistoryStatus.EMPTY else UNAVAILABLE_LINE
    return [header, absence]


def _fit(entries: list[PathHistory], budget: int) -> list[PathHistory]:
    """Fit sections under ``budget`` (AC-10).

    A prior finding carries a longer fixed prefix and more signal than a commit
    line, so commit lines are evicted first, longest first within the class.
    Every explored file keeps its header and a floor of one detail line, and a
    whole file is dropped only once no file can give up a line.
    """
    kept = {entry.path: entry for entry in entries}

    def cost() -> int:
        return estimate_tokens(
            "\n".join(line for entry in kept.values() for line in _section_lines(entry))
        )

    while kept and cost() > budget:
        if not _evict_detail(kept):
            del kept[min(kept, key=lambda path: _least_valuable(kept[path]))]
    return [kept[path] for path in sorted(kept)]


def _evict_detail(kept: dict[str, PathHistory]) -> bool:
    """Drop one detail line, commit lines before finding lines, floor of one."""
    for drop_commits in (True, False):
        candidates: list[tuple[str, int, int]] = []
        for path, entry in kept.items():
            if drop_commits:
                lines, siblings = entry.commit_lines, len(entry.finding_lines)
            else:
                lines, siblings = entry.finding_lines, len(entry.commit_lines)
            if len(lines) + siblings <= 1:
                continue
            candidates.extend((path, index, len(line)) for index, line in enumerate(lines))
        if not candidates:
            continue
        path, index, _ = max(candidates, key=lambda candidate: (candidate[2], candidate[0]))
        entry = kept[path]
        if drop_commits:
            kept[path] = replace(
                entry,
                commit_lines=entry.commit_lines[:index] + entry.commit_lines[index + 1 :],
            )
        else:
            kept[path] = replace(
                entry,
                finding_lines=entry.finding_lines[:index] + entry.finding_lines[index + 1 :],
            )
        return True
    return False


def _least_valuable(entry: PathHistory) -> tuple[int, int]:
    """Fewest surviving details first, then the largest, to converge fastest."""
    return (len(entry.detail_lines), -sum(len(line) for line in entry.detail_lines))


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_VALUE_CHARS:
        return text
    return text[: MAX_VALUE_CHARS - 1] + "…"
