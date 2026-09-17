from __future__ import annotations

import pytest

from critiq.apps.worker.push import push_patch


class _FakeClient:
    def __init__(
        self,
        ref_sha="sha-head",
        current_file_sha="blob-sha",
        protected=False,
        update_ok=True,
    ):
        self._ref_sha = ref_sha
        self._current_file_sha = current_file_sha
        self._protected = protected
        self._update_ok = update_ok
        self.calls = []

    async def get_ref(self, repo, ref):
        return self._ref_sha

    async def branch_protected(self, repo, branch):
        return self._protected

    async def get_file_sha(self, repo, path, ref):
        return self._current_file_sha

    async def update_file_content(self, repo, path, message, content, current_sha, branch):
        self.calls.append(
            {"repo": repo, "path": path, "content": content,
             "current_sha": current_sha, "branch": branch}
        )
        return {"commit": {"sha": "commit-sha-abc"}}


def _pr(fork=False):
    return {
        "head": {"ref": "feat", "repo": {"id": 1 if not fork else 999}},
        "base": {"repo": {"id": 1}},
    }


@pytest.mark.asyncio
async def test_push_success():
    client = _FakeClient()
    sha = await push_patch(
        client, "o/r", _pr(), "app/handler.py", "secure_code()", "sha-head"
    )
    assert sha == "commit-sha-abc"
    assert client.calls
    assert client.calls[0]["content"] == "secure_code()"


@pytest.mark.asyncio
async def test_push_returns_none_on_fork():
    sha = await push_patch(
        _FakeClient(), "o/r", _pr(fork=True), "app/handler.py", "x", "head-sha"
    )
    assert sha is None


@pytest.mark.asyncio
async def test_push_returns_none_when_branch_protected():
    sha = await push_patch(
        _FakeClient(protected=True),
        "o/r", _pr(), "app/handler.py", "x", "head-sha",
    )
    assert sha is None


@pytest.mark.asyncio
async def test_push_returns_none_on_ref_mismatch():
    sha = await push_patch(
        _FakeClient(ref_sha="different-sha"),
        "o/r", _pr(), "app/handler.py", "x", "head-sha",
    )
    assert sha is None
