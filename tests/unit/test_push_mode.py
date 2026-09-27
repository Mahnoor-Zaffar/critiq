from __future__ import annotations

import pytest

from critiq.apps.worker.push import push_patch
from critiq.apps.worker.tasks import _apply_push_mode
from critiq.core.findings import Finding, FindingSource, ReviewComment, ReviewResult
from critiq.core.policy import Category, ReviewPolicy, Severity

PUSH_POLICY = ReviewPolicy({"review": {"fix": {"enabled": True, "apply": "push"}}})


class _OrgApproved:
    async def __call__(self, session, repo):
        return True


class _FakeClient:
    """GitHub fake whose PR payload and live ref move independently."""

    def __init__(self, pr_head_sha, live_ref_sha, protected=False):
        self._pr_head_sha = pr_head_sha
        self._live_ref_sha = live_ref_sha
        self._protected = protected
        self.writes = []

    async def get_pull_request(self, repo, number):
        return {
            "head": {"sha": self._pr_head_sha, "ref": "feat", "repo": {"id": 1}},
            "base": {"sha": "base-sha", "repo": {"id": 1}},
        }

    async def get_ref(self, repo, ref):
        return self._live_ref_sha

    async def branch_protected(self, repo, branch):
        return self._protected

    async def get_file_sha(self, repo, path, ref):
        return "blob-sha"

    async def update_file_content(self, repo, path, message, content, current_sha, branch):
        self.writes.append(path)
        return {"commit": {"sha": "commit-sha-abc"}}


class _Patches:
    """Stands in for the verified patch set: one offered record."""

    def __init__(self, finding):
        self.finding = finding

    def __iter__(self):
        record = _Record(self.finding)
        yield record
        self.record = record


class _Record:
    def __init__(self, finding):
        self.finding = finding
        self.status = "offered"
        self.file_path = "app/logic.py"
        self.line_start = 1
        self.line_end = 1
        self.suggested_replacement = "    return value * factor"
        self.test_status = "passed"


def _finding() -> Finding:
    return Finding(
        category=Category.CORRECTNESS,
        file_path="app/logic.py",
        title="scale adds instead of multiplying",
        explanation="e",
        evidence="e",
        recommendation="r",
        severity=Severity.HIGH,
        confidence=0.95,
        line_start=1,
        line_end=1,
        source=FindingSource.STATIC,
    )


def _result(finding, head_sha) -> ReviewResult:
    comment = ReviewComment(
        file_path="app/logic.py",
        body="```suggestion\n    return value * factor\n```",
        start_line=1,
        end_line=1,
        finding=finding,
    )
    return ReviewResult(
        decision="COMMENT",
        risk="medium",
        summary="one finding",
        comments=[comment],
        findings=[finding],
        patches=_Patches(finding),
        head_sha=head_sha,
    )


@pytest.fixture(autouse=True)
def _org_push_enabled(monkeypatch):
    monkeypatch.setattr("critiq.apps.worker.tasks.org_push_enabled", _OrgApproved())


@pytest.mark.asyncio
async def test_pushes_when_live_head_matches_tested_head():
    finding = _finding()
    result = _result(finding, "tested-sha")
    client = _FakeClient(pr_head_sha="tested-sha", live_ref_sha="tested-sha")

    state = await _apply_push_mode(
        client, "acme/widgets", 9, None, PUSH_POLICY, result
    )

    assert client.writes == ["app/logic.py"]
    assert state.commits == {id(finding): "commit-sha-abc"}
    assert result.comments == []
    assert "Pushed auto-fix commits" in result.summary


@pytest.mark.asyncio
async def test_head_moved_after_review_aborts_push_and_keeps_suggestion():
    """AC-5: live ref differs from the head the patch was tested against."""
    finding = _finding()
    result = _result(finding, "tested-sha")
    client = _FakeClient(pr_head_sha="moved-sha", live_ref_sha="moved-sha")

    state = await _apply_push_mode(
        client, "acme/widgets", 9, None, PUSH_POLICY, result
    )

    assert client.writes == []
    assert state.commits == {}
    assert len(result.comments) == 1
    assert "```suggestion" in result.comments[0].body
    assert "Pushed auto-fix commits" not in result.summary


@pytest.mark.asyncio
async def test_no_recorded_tested_head_aborts_push():
    """Without a recorded tested head there is nothing to compare, so no push."""
    finding = _finding()
    result = _result(finding, None)
    client = _FakeClient(pr_head_sha="moved-sha", live_ref_sha="moved-sha")

    state = await _apply_push_mode(
        client, "acme/widgets", 9, None, PUSH_POLICY, result
    )

    assert client.writes == []
    assert state.commits == {}
    assert len(result.comments) == 1


@pytest.mark.asyncio
async def test_push_patch_still_compares_live_ref_to_given_tested_sha():
    """The low level guard itself is unchanged and still refuses a stale sha."""
    client = _FakeClient(pr_head_sha="new-sha", live_ref_sha="new-sha")
    sha = await push_patch(
        client,
        "acme/widgets",
        {"head": {"ref": "feat", "repo": {"id": 1}}, "base": {"repo": {"id": 1}}},
        "app/logic.py",
        "    return value * factor",
        "old-sha",
    )
    assert sha is None
    assert client.writes == []
