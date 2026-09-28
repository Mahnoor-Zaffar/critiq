import asyncio
from unittest.mock import MagicMock

import pytest

from critiq.ai.history import (
    EMPTY_LINE,
    MAX_FILES,
    MAX_VALUE_CHARS,
    REVIEWER_TOKEN_BUDGET,
    SYNTHESIS_TOKEN_BUDGET,
    UNAVAILABLE_LINE,
    HistoryBlock,
    HistoryStatus,
    PathHistory,
    _fit,
    _truncate,
    collect_history,
    render_history,
)
from critiq.ai.reviewers import build_reviewers, read_synthesis_prompt
from critiq.ai.tokens import estimate_tokens
from critiq.analysis.diff import DiffHunk, FileDiff
from critiq.core.policy import ReviewPolicy
from critiq.integrations.github.client import GitHubClientError

PATHS = ["app/a.py", "app/b.py", "app/c.py"]


def _diff(path: str, added: int = 1) -> FileDiff:
    return FileDiff(
        path=path,
        hunks=[DiffHunk(0, 0, 1, added, added_lines=list(range(1, added + 1)))],
    )


DIFFS = [_diff(path) for path in PATHS]


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

    def __init__(self, rows=None, fail_paths=None):
        self.rows = (
            rows
            if rows is not None
            else {
                "app/a.py": [("app/a.py", "missing auth check", "security", 42)],
                "app/b.py": [],
                "app/c.py": [],
            }
        )
        self.fail_paths = fail_paths or set()

    async def execute(self, stmt):
        params = stmt.compile().params
        path = next((v for k, v in params.items() if k.startswith("file_path")), "")
        if path in self.fail_paths:
            raise RuntimeError("connection reset")
        return MagicMock(all=lambda: self.rows.get(path, []))


class ConcurrentUseGuardSession(FakeSession):
    """Mirrors AsyncSession's ban on concurrent use of one connection."""

    def __init__(self, rows=None):
        super().__init__(rows)
        self.in_flight = 0
        self.peak_in_flight = 0

    async def execute(self, stmt):
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        if self.in_flight > 1:
            raise RuntimeError("concurrent operations are not permitted")
        try:
            await asyncio.sleep(0)
            return await super().execute(stmt)
        finally:
            self.in_flight -= 1


def _lines_for(rendered: str, path: str) -> list[str]:
    """The lines a render attributed to one file."""
    out: list[str] = []
    keeping = False
    for line in rendered.splitlines():
        if line.startswith("History Context for "):
            keeping = line == f"History Context for {path}"
        elif keeping:
            out.append(line)
    return out


class FakeProvider:
    async def generate(self, *, system, user, schema=None):
        return {"findings": []}


# --- collection: status honesty (AC-7, AC-8, AC-9) -------------------------


@pytest.mark.asyncio
async def test_happy_path_records_status_per_path():
    block = await collect_history(FakeClient(), FakeSession(), "o/r", "base123", DIFFS)

    assert block.entry("app/a.py").status is HistoryStatus.OK
    assert block.entry("app/a.py").commit_lines == ("- Changed in abc1234: fix null check",)
    assert block.entry("app/a.py").finding_lines == (
        "- Previously flagged in Run 42 (security): missing auth check",
    )
    assert block.entry("app/b.py").status is HistoryStatus.OK
    assert block.entry("app/c.py").status is HistoryStatus.EMPTY
    assert block.changed_file_count == 3
    assert block.explored_paths == PATHS


@pytest.mark.asyncio
async def test_only_a_confirmed_empty_record_claims_no_recorded_history():
    block = await collect_history(
        FakeClient(commits={path: [] for path in PATHS}),
        FakeSession(rows={}),
        "o/r",
        "base123",
        DIFFS,
    )
    for path in PATHS:
        assert block.entry(path).status is HistoryStatus.EMPTY
        assert EMPTY_LINE in render_history(block, {path})


@pytest.mark.asyncio
async def test_a_failed_lookup_renders_unavailable_not_no_recorded_history():
    block = await collect_history(
        FakeClient(error_paths=set(PATHS)),
        FakeSession(rows={}),
        "o/r",
        "base123",
        DIFFS,
    )
    for path in PATHS:
        assert block.entry(path).status is HistoryStatus.UNAVAILABLE
        rendered = render_history(block, {path})
        assert UNAVAILABLE_LINE in rendered
        assert EMPTY_LINE not in rendered


@pytest.mark.asyncio
async def test_a_partial_failure_still_shows_whatever_was_learned():
    """The commits leg failed, but the database leg found a prior finding."""
    block = await collect_history(
        FakeClient(error_paths=set(PATHS)), FakeSession(), "o/r", "base123", DIFFS
    )
    entry = block.entry("app/a.py")
    assert entry.status is HistoryStatus.OK
    assert entry.commit_lines == ()
    assert entry.finding_lines == ("- Previously flagged in Run 42 (security): missing auth check",)
    for path in ("app/b.py", "app/c.py"):
        assert block.entry(path).status is HistoryStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_a_failed_database_lookup_is_unavailable_rather_than_empty():
    block = await collect_history(
        FakeClient(commits={path: [] for path in PATHS}),
        FakeSession(rows={}, fail_paths=set(PATHS)),
        "o/r",
        "base123",
        DIFFS,
    )
    for path in PATHS:
        assert block.entry(path).status is HistoryStatus.UNAVAILABLE
        assert EMPTY_LINE not in render_history(block, {path})


@pytest.mark.asyncio
async def test_a_missing_session_is_unavailable_rather_than_empty():
    block = await collect_history(
        FakeClient(commits={path: [] for path in PATHS}), None, "o/r", "base123", DIFFS
    )
    for path in PATHS:
        assert block.entry(path).status is HistoryStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_a_missing_base_sha_is_unavailable_not_empty():
    client = FakeClient()
    block = await collect_history(client, FakeSession(), "o/r", "", DIFFS)

    assert client.requested == [], "a missing base SHA must not be queried as if it were a ref"
    for path in PATHS:
        assert block.entry(path).status is HistoryStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_one_failed_file_keeps_the_other_files_history():
    block = await collect_history(
        FakeClient(error_paths={"app/b.py"}), FakeSession(), "o/r", "base123", DIFFS
    )
    assert block.entry("app/a.py").status is HistoryStatus.OK
    assert block.entry("app/b.py").status is HistoryStatus.UNAVAILABLE
    assert "- Changed in abc1234" in render_history(block, {"app/a.py"})
    assert UNAVAILABLE_LINE in render_history(block, {"app/b.py"})


@pytest.mark.asyncio
async def test_collection_never_raises():
    class Exploding(FakeClient):
        async def get_recent_commits(self, repo, sha, path, per_page=3):
            raise RuntimeError("boom")

    block = await collect_history(Exploding(), FakeSession(rows={}), "o/r", "base123", DIFFS)
    assert block.entry("app/a.py").status is HistoryStatus.UNAVAILABLE
    assert render_history(block) != "", "the block still renders, it just has nothing to say"


@pytest.mark.asyncio
async def test_commits_are_queried_against_the_base_ref():
    client = FakeClient()
    await collect_history(client, FakeSession(), "o/r", "mergebase123", DIFFS)

    assert client.requested, "expected a commits query per changed file"
    assert all(sha == "mergebase123" for _, sha, _, _ in client.requested)
    assert all(per_page == 3 for *_, per_page in client.requested)


@pytest.mark.asyncio
async def test_at_most_three_commits_and_five_findings_are_kept():
    commits = {
        path: [{"sha": f"{i:07d}abc", "message": f"commit {i}"} for i in range(9)]
        for path in PATHS
    }
    rows = {
        path: [(path, f"finding {i}", "security", i) for i in range(9)] for path in PATHS
    }
    block = await collect_history(
        FakeClient(commits=commits), FakeSession(rows=rows), "o/r", "base123", DIFFS
    )
    for path in PATHS:
        assert len(block.entry(path).commit_lines) == 3
        assert len(block.entry(path).finding_lines) == 5


# --- collection: exploration cap (AC-7, AC-9) -----------------------------


@pytest.mark.asyncio
async def test_explored_files_are_the_largest_by_added_lines_ties_by_path():
    # f02 and f03 tie on added lines, so the path breaks the tie.
    added = [1, 5, 4, 4, 3, 100, 99, 98, 97, 96, 95, 94, 93]
    diffs = [_diff(f"app/f{i:02d}.py", added=count) for i, count in enumerate(added)]
    client = FakeClient(commits={fd.path: [] for fd in diffs})
    block = await collect_history(client, FakeSession(rows={}), "o/r", "base123", diffs)

    queried = {path for _, _, path, _ in client.requested}
    assert len(queried) == MAX_FILES
    # Descending added line count, with the f02/f03 tie broken by path.
    assert queried == {
        "app/f05.py", "app/f06.py", "app/f07.py", "app/f08.py", "app/f09.py",
        "app/f10.py", "app/f11.py", "app/f12.py", "app/f01.py", "app/f02.py",
    }
    assert block.entry("app/f03.py").status is HistoryStatus.NOT_EXPLORED
    assert block.changed_file_count == len(diffs)


@pytest.mark.asyncio
async def test_files_beyond_the_cap_render_unavailable_as_not_explored():
    diffs = [_diff(f"app/f{i}.py", added=100 - i) for i in range(MAX_FILES + 3)]
    block = await collect_history(
        FakeClient(commits={fd.path: [] for fd in diffs}),
        FakeSession(rows={}),
        "o/r",
        "base123",
        diffs,
    )
    beyond = diffs[MAX_FILES:]
    for fd in beyond:
        assert block.entry(fd.path).status is HistoryStatus.NOT_EXPLORED
        rendered = render_history(block, {fd.path})
        assert UNAVAILABLE_LINE in rendered
        assert EMPTY_LINE not in rendered

    rendered = render_history(block)
    assert f"Recorded history for {MAX_FILES} of {MAX_FILES + 3} changed files." in rendered
    for fd in beyond:
        assert fd.path not in rendered, "a file past the cap is named as unexplored, not listed"


# --- collection: concurrency and deadlines (AC-8, AC-10) -------------------


class DelayedClient(FakeClient):
    async def get_recent_commits(self, repo, sha, path, per_page=3):
        self.requested.append((repo, sha, path, per_page))
        if path in ("app/b.py", "app/c.py"):
            await asyncio.sleep(10)
        return self.commits.get(path, [])


@pytest.mark.asyncio
async def test_deadline_keeps_whatever_arrived_and_marks_the_rest_unavailable():
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
    assert "- Changed in abc1234: fast win" in render_history(block, {"app/a.py"})
    for path in ("app/b.py", "app/c.py"):
        assert block.entry(path).status is HistoryStatus.UNAVAILABLE
        assert EMPTY_LINE not in render_history(block, {path})


@pytest.mark.asyncio
async def test_per_call_timeout_bounds_one_slow_file():
    class OneSlow(FakeClient):
        async def get_recent_commits(self, repo, sha, path, per_page=3):
            self.requested.append((repo, sha, path, per_page))
            if path == "app/b.py":
                await asyncio.sleep(10)
            return self.commits.get(path, [])

    block = await collect_history(
        OneSlow(), FakeSession(), "o/r", "base123", DIFFS, per_call_timeout=0.05
    )
    assert block.entry("app/b.py").status is HistoryStatus.UNAVAILABLE
    assert block.entry("app/a.py").status is HistoryStatus.OK


@pytest.mark.asyncio
async def test_database_query_is_bounded_by_a_timeout():
    class SlowSession(FakeSession):
        async def execute(self, stmt):
            await asyncio.sleep(10)
            return MagicMock(all=lambda: [])

    block = await collect_history(
        FakeClient(commits={path: [] for path in PATHS}),
        SlowSession(),
        "o/r",
        "base123",
        DIFFS,
        db_timeout=0.05,
    )
    for path in PATHS:
        assert block.entry(path).status is HistoryStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_concurrency_is_bounded():
    peak = 0
    active = 0

    async def tracked(repo, sha, path, per_page=3):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return [{"sha": "abc1234567", "message": "m"}]

    many = [_diff(f"app/f{i}.py") for i in range(8)]
    client = FakeClient()
    client.get_recent_commits = tracked
    await collect_history(client, FakeSession(), "o/r", "base123", many)
    assert peak <= 4


@pytest.mark.asyncio
async def test_the_session_is_never_used_concurrently_and_every_file_gets_findings():
    paths = [f"app/f{i}.py" for i in range(6)]
    diffs = [_diff(path) for path in paths]
    client = FakeClient(
        commits={path: [{"sha": "abc1234567", "message": "tweak"}] for path in paths}
    )
    session = ConcurrentUseGuardSession(
        rows={path: [(path, f"finding in {path}", "security", 42)] for path in paths}
    )

    block = await collect_history(client, session, "o/r", "base123", diffs)

    assert session.peak_in_flight == 1
    for path in paths:
        assert f"- Previously flagged in Run 42 (security): finding in {path}" in render_history(
            block, {path}
        )


# --- bounding values at the source (AC-9) ---------------------------------


def test_truncate_caps_a_value_at_the_budget():
    assert _truncate("short") == "short"
    truncated = _truncate("x" * 500)
    assert len(truncated) == MAX_VALUE_CHARS
    assert truncated.endswith("…")


@pytest.mark.asyncio
async def test_long_values_are_truncated_at_collection():
    client = FakeClient(
        commits={"app/a.py": [{"sha": "abc1234567", "message": "c" * 400}]}
    )
    session = FakeSession(
        rows={"app/a.py": [("app/a.py", "f" * 400, "security", 7)]}
    )
    block = await collect_history(
        client, session, "o/r", "base123", [_diff("app/a.py")]
    )
    entry = block.entry("app/a.py")
    assert len(entry.commit_lines[0]) == len("- Changed in abc1234: ") + MAX_VALUE_CHARS
    assert len(entry.finding_lines[0]) == len(
        "- Previously flagged in Run 7 (security): "
    ) + MAX_VALUE_CHARS


# --- rendering: scoping and budgets (AC-7, AC-9, AC-10) ------------------


def _worst_case_entry(index: int, path: str | None = None) -> PathHistory:
    path = path or f"src/{'n' * 51}/mod{index}.py"
    return PathHistory(
        path,
        HistoryStatus.OK,
        tuple(f"- Changed in {index}{i:06d}: {'c' * MAX_VALUE_CHARS}" for i in range(3)),
        tuple(
            f"- Previously flagged in Run {index}{i} (security): {'f' * MAX_VALUE_CHARS}"
            for i in range(5)
        ),
    )


def test_a_worst_case_file_never_trims_in_the_reviewer_render():
    entry = _worst_case_entry(0)
    block = HistoryBlock(entries={entry.path: entry}, changed_file_count=1)

    rendered = render_history(block, {entry.path}, budget=REVIEWER_TOKEN_BUDGET)

    assert rendered.splitlines()[1:] == list(entry.detail_lines)
    assert estimate_tokens(rendered) <= REVIEWER_TOKEN_BUDGET


def test_the_reviewer_render_carries_only_the_file_it_is_judging():
    entries = {f"app/f{i}.py": _worst_case_entry(i, path=f"app/f{i}.py") for i in range(4)}
    block = HistoryBlock(entries=entries, changed_file_count=4)

    rendered = render_history(block, {"app/f1.py"})

    assert "app/f1.py" in rendered
    for other in ("app/f0.py", "app/f2.py", "app/f3.py"):
        assert other not in rendered


def test_an_unknown_path_renders_unavailable():
    assert UNAVAILABLE_LINE in render_history(HistoryBlock(), {"app/ghost.py"})


def test_a_block_with_nothing_explored_renders_empty():
    block = HistoryBlock(
        entries={"app/a.py": PathHistory("app/a.py", HistoryStatus.NOT_EXPLORED)},
        changed_file_count=1,
    )
    assert render_history(block) == ""


def test_render_history_tolerates_no_block():
    assert render_history(None) == ""
    assert render_history(None, {"app/a.py"}) == ""


def test_the_synthesizer_render_stays_under_budget():
    entries = {f"src/{'n' * 51}/mod{i}.py": _worst_case_entry(i) for i in range(MAX_FILES)}
    block = HistoryBlock(entries=entries, changed_file_count=MAX_FILES)

    rendered = render_history(block)

    assert estimate_tokens(rendered) <= SYNTHESIS_TOKEN_BUDGET
    assert rendered.splitlines()[0] == (
        f"Recorded history for {MAX_FILES} of {MAX_FILES} changed files."
    )


def test_trimming_removes_commit_lines_before_prior_finding_lines():
    entries = {f"src/{'n' * 51}/mod{i}.py": _worst_case_entry(i) for i in range(MAX_FILES)}
    block = HistoryBlock(entries=entries, changed_file_count=MAX_FILES)

    rendered = render_history(block)

    assert "- Previously flagged" in rendered
    assert "- Changed in" not in rendered, "commit lines carry the least signal and go first"


def test_trimming_keeps_attribution_and_the_one_detail_floor():
    entries = {f"src/{'n' * 51}/mod{i}.py": _worst_case_entry(i) for i in range(MAX_FILES)}
    block = HistoryBlock(entries=entries, changed_file_count=MAX_FILES)

    lines = render_history(block).splitlines()

    current: str | None = None
    per_file: dict[str, int] = {}
    for line in lines:
        if line.startswith("History Context for "):
            current = line.removeprefix("History Context for ")
            per_file.setdefault(current, 0)
        elif current is not None:
            per_file[current] += 1
    assert per_file, "expected at least one surviving file"
    assert min(per_file.values()) >= 1, (
        "every surviving file keeps at least one detail line under its own header"
    )
    assert set(per_file) <= set(entries)


def test_trimming_drops_whole_files_rather_than_bare_headers():
    entries = {f"src/{'n' * 51}/mod{i}.py": _worst_case_entry(i) for i in range(MAX_FILES)}
    block = HistoryBlock(entries=entries, changed_file_count=MAX_FILES)

    rendered = render_history(block, budget=200)

    lines = rendered.splitlines()
    headers = [i for i, line in enumerate(lines) if line.startswith("History Context for ")]
    assert len(headers) < MAX_FILES, "a 200 token budget cannot hold ten worst case files"
    for index in headers:
        following = lines[index + 1] if index + 1 < len(lines) else ""
        assert following.startswith("- "), "a header was left without a detail line"


def test_fit_keeps_the_most_valuable_lines_when_over_budget():
    entries = [_worst_case_entry(i) for i in range(MAX_FILES)]
    kept = _fit(entries, budget=200)

    assert kept
    for entry in kept:
        assert entry.detail_lines, "a kept file must keep a detail line"
        assert estimate_tokens(
            "\n".join(
                [f"History Context for {e.path}" for e in kept]
                + [line for e in kept for line in e.detail_lines]
            )
        ) <= 200


def test_fit_returns_everything_when_under_budget():
    entries = [_worst_case_entry(0)]
    assert _fit(entries, budget=SYNTHESIS_TOKEN_BUDGET) == entries


@pytest.mark.asyncio
async def test_the_synthesizer_lines_are_a_superset_of_the_reviewer_lines():
    block = await collect_history(FakeClient(), FakeSession(), "o/r", "base123", DIFFS)

    full = render_history(block)
    for path in block.explored_paths:
        reviewer_lines = _lines_for(render_history(block, {path}), path)
        assert set(reviewer_lines) <= set(_lines_for(full, path))


@pytest.mark.asyncio
async def test_parity_holds_for_a_block_big_enough_to_be_trimmed():
    paths = [f"app/f{i}.py" for i in range(MAX_FILES)]
    diffs = [_diff(path) for path in paths]
    client = FakeClient(
        commits={p: [{"sha": f"abc{i:04d}", "message": f"commit {i}"}] for i, p in enumerate(paths)}
    )
    session = FakeSession(
        rows={p: [(p, f"finding {i}", "security", i) for i in range(3)] for p in paths}
    )
    block = await collect_history(client, session, "o/r", "base123", diffs)

    full = render_history(block)
    for path in block.explored_paths:
        reviewer_lines = _lines_for(render_history(block, {path}), path)
        synth_lines = set(_lines_for(full, path))
        # A file the synthesizer dropped whole is absent, not contradicted: the
        # reviewer only ever carries history, never a claim the block denies.
        if path in full:
            assert set(reviewer_lines) <= synth_lines
        else:
            assert reviewer_lines and synth_lines == set()


# --- telling the model (AC-9) ---------------------------------------------


def test_every_reviewer_prompt_tells_the_model_history_exists():
    reviewers = build_reviewers(FakeProvider(), ReviewPolicy.defaults())
    assert len(reviewers) == 6
    for reviewer in reviewers:
        assert "Recorded history" in reviewer.system_prompt
        assert "never a finding to repeat" in reviewer.system_prompt


def test_the_synthesis_prompt_lets_the_model_cite_history():
    prompt = read_synthesis_prompt()
    assert "the recorded history" in prompt
    assert "Only reference the provided findings;" not in prompt, (
        "the old rule forbade citing history, which is the block this feature provides"
    )
