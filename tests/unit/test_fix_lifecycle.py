from __future__ import annotations

import pytest

from critiq.apps.worker.auto_fix import PatchRecord
from critiq.apps.worker.fix_lifecycle import (
    org_push_enabled,
    push_if_allowed,
    save_patch_rows,
)
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, Severity

PATCH = """@@ -1,3 +1,4 @@
  def handler():
+    import os
      x = call()
+    os.system(x)
"""


def _finding(pk=0) -> Finding:
    return Finding(
        category=Category.SECURITY,
        file_path="handler.py",
        title="os.system",
        explanation="Shell command.",
        evidence="`os.system(x)`",
        recommendation="Use subprocess.",
        severity=Severity.HIGH,
        confidence=0.9,
        line_start=4,
        line_end=4,
        source=FindingSource.STATIC,
    )


def _record(finding: Finding, status="offered") -> PatchRecord:
    return PatchRecord(
        finding=finding,
        file_path="handler.py",
        line_start=4,
        line_end=4,
        version=1,
        status=status,
        test_status="passed",
        suggested_replacement="    subprocess.run([x], shell=False)",
    )


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def scalar(self, stmt):
        return None

    async def get(self, model, pk):
        return None


# -- save_patch_rows --

def test_save_patch_rows_persists_offered_records():
    session = _FakeSession()
    finding = _finding()
    rows = __import__("asyncio").run(
        save_patch_rows(
            session,
            run_id=7,
            finding_map={id(finding): 9},
            patches=[_record(finding)],
        )
    )
    assert len(rows) == 1
    assert rows[0].review_run_id == 7
    assert rows[0].finding_id == 9
    assert rows[0].status == "offered"
    assert rows[0].test_status == "passed"
    assert rows[0].version == 1
    assert session.commits == 1


def test_save_patch_rows_records_commit_sha_as_applied():
    session = _FakeSession()
    finding = _finding()
    import asyncio

    result = asyncio.run(
        save_patch_rows(
            session,
            run_id=7,
            finding_map={id(finding): 9},
            patches=[_record(finding)],
            commit_sha_by_finding={id(finding): "abc123"},
        )
    )
    assert result[0].status == "applied"
    assert result[0].commit_sha == "abc123"


def test_save_patch_rows_records_comment_id():
    session = _FakeSession()
    finding = _finding()
    import asyncio

    result = asyncio.run(
        save_patch_rows(
            session,
            run_id=7,
            finding_map={id(finding): 9},
            patches=[_record(finding)],
            review_comment_id_by_finding={id(finding): 55},
        )
    )
    assert result[0].review_comment_id == 55


def test_save_patch_rows_skips_unpersisted_finding():
    session = _FakeSession()
    import asyncio

    result = asyncio.run(
        save_patch_rows(
            session,
            run_id=7,
            finding_map={},
            patches=[_record(_finding())],
        )
    )
    assert result == []


# -- push_if_allowed --

class _FakeGitHubClient:
    def __init__(self, sha="head-sha", push_exception=None):
        self.sha = sha
        self.push_exception = push_exception
        self.update_calls = 0

    async def get_ref(self, repo, ref):
        return self.sha

    async def branch_protected(self, repo, branch):
        return False

    async def get_file_sha(self, repo, path, ref):
        return "blob-sha"

    async def update_file_content(self, repo, path, message, content, current_sha, branch):
        self.update_calls += 1
        if self.push_exception:
            raise self.push_exception
        return {"commit": {"sha": "commit-sha"}}  # pragma: no cover


def _pr(fork=False):
    return {
        "head": {"ref": "feat-x", "repo": {"id": 1 if not fork else 999}},
        "base": {"repo": {"id": 1}},
    }


@pytest.mark.asyncio
async def test_push_if_allowed_pushes_offered_patch():
    finding = _finding()
    client = _FakeGitHubClient()
    commits, remaining = await push_if_allowed(
        client, "o/r", _pr(), [_record(finding)], "head-sha"
    )
    assert commits == {id(finding): "commit-sha"}
    assert remaining == []


@pytest.mark.asyncio
async def test_push_if_allowed_keeps_fork_patches_as_suggestions():
    finding = _finding()
    client = _FakeGitHubClient()
    commits, remaining = await push_if_allowed(
        client, "o/r", _pr(fork=True), [_record(finding)], "head-sha"
    )
    assert commits == {}
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_push_if_allowed_aborts_on_ref_mismatch():
    finding = _finding()
    client = _FakeGitHubClient(sha="moved-ref")
    commits, remaining = await push_if_allowed(
        client, "o/r", _pr(), [_record(finding)], "head-sha"
    )
    assert commits == {}
    assert len(remaining) == 1
    assert client.update_calls == 0


@pytest.mark.asyncio
async def test_push_if_allowed_keeps_non_offered_patches():
    finding = _finding()
    client = _FakeGitHubClient()
    commits, remaining = await push_if_allowed(
        client, "o/r", _pr(), [_record(finding, status="failed")], "head-sha"
    )
    assert commits == {}
    assert len(remaining) == 1


# -- org_push_enabled --

class _Repo:
    def __init__(self, pk):
        self.id = pk


class _Setting:
    def __init__(self, enabled):
        self.auto_push_enabled = enabled


class _ScalarByQuery:
    def __init__(self, repo=None, setting=None):
        self._repo = repo
        self._setting = setting

    async def scalar(self, stmt):
        stmt_s = " ".join(str(stmt).split())
        if "FROM repositories" in stmt_s:
            return self._repo
        return self._setting


def test_org_push_enabled_false_without_repo():
    session = _FakeSession()
    import asyncio
    assert asyncio.run(org_push_enabled(session, "o/r")) is False


def test_org_push_enabled_false_without_setting():
    session = _ScalarByQuery(repo=_Repo(3), setting=None)
    import asyncio
    assert asyncio.run(org_push_enabled(session, "o/r")) is False


def test_org_push_enabled_true():
    session = _ScalarByQuery(repo=_Repo(3), setting=_Setting(True))
    import asyncio
    assert asyncio.run(org_push_enabled(session, "o/r")) is True
