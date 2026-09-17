import asyncio
from unittest.mock import MagicMock

import pytest

from critiq.ai.history import _fit_budget, _token_cost, collect_history
from critiq.analysis.diff import FileDiff
from critiq.integrations.github.client import GitHubClientError

PATHS = ["app/a.py", "app/b.py", "app/c.py"]
DIFFS = [FileDiff(path=path) for path in PATHS]


class FakeClient:
    def __init__(self, commits=None, error_paths=None):
        self.commits = commits or {
            "app/a.py": [{"sha": "abc1234567", "message": "fix null check"}],
            "app/b.py": [{"sha": "def9012345", "message": "add retry around DB call"}],
            "app/c.py": [],
        }
        self.error_paths = error_paths or set()
        self.requested = []

    async def get_recent_commits(self, repo, sha, path, per_page=3):
        self.requested.append((repo, sha, path, per_page))
        if path in self.error_paths:
            raise GitHubClientError(f"GET commits -> 500 for {path}")
        return self.commits.get(path, [])


class FakeSession:
    """Returns findings rows per changed file, matching the SQL's file_path bind."""

    def __init__(self, rows=None):
        self.rows = (
            rows
            if rows is not None
            else {
                "app/a.py": [("app/a.py", "missing auth check", "security", 42)],
                "app/b.py": [],
                "app/c.py": [],
            }
        )

    async def execute(self, stmt):
        params = stmt.compile().params
        path = next((v for k, v in params.items() if k.startswith("file_path")), "")
        rows = self.rows.get(path, [])
        return MagicMock(all=lambda: rows)


@pytest.mark.asyncio
async def test_collect_history_happy_path():
    block = await collect_history(FakeClient(), FakeSession(), "o/r", "base123", DIFFS)

    assert "app/a.py" in block
    assert "- Changed in abc1234: fix null check" in block
    assert "- Previously flagged in Run 42 (security): missing auth check" in block
    assert "- Changed in def9012: add retry around DB call" in block
    assert block.index("app/a.py") < block.index("app/b.py")
    assert _token_cost(block.splitlines()) <= 1200


@pytest.mark.asyncio
async def test_commits_queried_against_the_base_ref():
    client = FakeClient()
    await collect_history(client, FakeSession(), "o/r", "mergebase123", DIFFS)

    assert client.requested, "expected a commits query per changed file"
    assert all(sha == "mergebase123" for _, sha, _, _ in client.requested)
    assert all(per_page == 3 for *_, per_page in client.requested)


@pytest.mark.asyncio
async def test_new_file_with_no_history_yields_empty_block():
    client = FakeClient(commits={path: [] for path in PATHS})
    block = await collect_history(client, FakeSession(rows={}), "o/r", "base123", DIFFS)
    assert block == ""


@pytest.mark.asyncio
async def test_total_failure_returns_empty_block_and_never_raises():
    client = FakeClient(error_paths=set(PATHS))
    block = await collect_history(client, FakeSession(), "o/r", "base123", DIFFS)
    assert block == ""


@pytest.mark.asyncio
async def test_single_file_failure_keeps_other_files():
    client = FakeClient(error_paths={"app/b.py"})
    block = await collect_history(client, FakeSession(), "o/r", "base123", DIFFS)
    assert "app/a.py" in block
    assert "app/b.py" not in block
    assert "app/c.py" not in block


class DelayedClient(FakeClient):
    async def get_recent_commits(self, repo, sha, path, per_page=3):
        self.requested.append((repo, sha, path, per_page))
        if path in ("app/b.py", "app/c.py"):
            await asyncio.sleep(10)
        return self.commits.get(path, [])


@pytest.mark.asyncio
async def test_deadline_keeps_whatever_history_arrived():
    client = DelayedClient(
        commits={
            "app/a.py": [{"sha": "abc1234567", "message": "fast win"}],
            "app/b.py": [],
            "app/c.py": [],
        }
    )
    block = await collect_history(
        client, FakeSession(), "o/r", "base123", DIFFS, aggregate_deadline=0.05
    )
    assert "fast win" in block
    assert "slow" not in block


@pytest.mark.asyncio
async def test_concurrency_is_bounded():
    calls = 0
    active = 0
    peak = 0

    async def tracked(repo, sha, path, per_page=3):
        nonlocal calls, active, peak
        calls += 1
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return [{"sha": "abc1234567", "message": "m"}]

    many = [FileDiff(path=f"app/f{i}.py") for i in range(8)]
    client = FakeClient()
    client.get_recent_commits = tracked
    await collect_history(client, FakeSession(), "o/r", "base123", many)
    assert calls == 8
    assert peak <= 4


def test_fit_budget_cuts_longest_entries_first():
    filler = [f"- Changed in {i:07d}: {'x' * 120}" for i in range(200)]
    short_lines = ["app/a.py", "- Changed in abc1234: fix", "- Changed in def9012: retry"]
    fitted = _fit_budget(filler + short_lines)
    assert _token_cost(fitted) <= 1200
    assert all(line in fitted for line in short_lines)


def test_fit_budget_returns_untouched_lines_when_under_budget():
    lines = ["app/a.py", "- Changed in abc1234: fix"]
    assert _fit_budget(lines) == lines
