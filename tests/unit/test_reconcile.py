from __future__ import annotations

import pytest

from critiq.apps.worker.reconcile import reconcile_patches


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, patches=None, run=None):
        self._patches = patches or []
        self._run = run
        self.committed = False

    async def scalar(self, stmt):
        return self._run

    async def scalars(self, stmt):
        return _FakeScalars(self._patches)

    async def commit(self):
        self.committed = True

    async def get(self, model, pk):
        return None


class _FakeClient:
    def __init__(self, head_source=None, basis_in_diff=True, comment_body="old"):
        self._head_source = head_source
        self._basis_in_diff = basis_in_diff
        self._comment_body = comment_body
        self.updated_comments = []

    async def get_file_content(self, repo, path, ref):
        return self._head_source

    async def patch_diff_basis(self, repo, number, path, line):
        return self._basis_in_diff

    async def get_review_comment(self, repo, comment_id):
        return self._comment_body

    async def update_review_comment(self, repo, comment_id, body):
        self.updated_comments.append((comment_id, body))
        return {}


class _FakePatch:
    def __init__(
        self,
        pk=1,
        status="offered",
        file_path="app/handler.py",
        line_start=3,
        line_end=3,
        version=1,
        replacement_text="secure_code()",
        finding_id=1,
        review_comment_id=None,
    ):
        self.id = pk
        self.status = status
        self.file_path = file_path
        self.line_start = line_start
        self.line_end = line_end
        self.version = version
        self.replacement_text = replacement_text
        self.finding_id = finding_id
        self.review_comment_id = review_comment_id


class _FakeRun:
    def __init__(self, pk=1):
        self.id = pk


# -- applied path --

@pytest.mark.asyncio
async def test_reconcile_applied_when_replacement_present():
    patch = _FakePatch(status="offered")
    client = _FakeClient(head_source="secure_code() exists here")
    session = _FakeSession(patches=[patch], run=_FakeRun())

    result = await reconcile_patches(
        client, "o/r", 1, "sha123", "synchronize", session
    )

    assert result == []
    assert patch.status == "applied"
    assert session.committed


# -- rejected path --

@pytest.mark.asyncio
async def test_reconcile_rejected_when_basis_gone():
    patch = _FakePatch(status="offered")
    client = _FakeClient(head_source="totally different code", basis_in_diff=False)
    session = _FakeSession(patches=[patch], run=_FakeRun())

    result = await reconcile_patches(
        client, "o/r", 1, "sha123", "reopened", session
    )

    assert result == []
    assert patch.status == "rejected"


# -- regenerate path --

@pytest.mark.asyncio
async def test_reconcile_regenerate_when_hunk_moved():
    patch = _FakePatch(status="offered", version=1)
    client = _FakeClient(head_source="old code here, no replacement")
    session = _FakeSession(patches=[patch], run=_FakeRun())

    result = await reconcile_patches(
        client, "o/r", 1, "sha123", "synchronize", session
    )

    assert len(result) == 1
    assert result[0]["version"] == 2
    assert result[0]["file_path"] == "app/handler.py"
    assert patch.version == 2
    assert session.committed


@pytest.mark.asyncio
async def test_reconcile_regenerate_notes_supersession_in_prior_comment():
    patch = _FakePatch(
        status="offered", version=1, review_comment_id=77
    )
    client = _FakeClient(head_source="old code here, no replacement")
    session = _FakeSession(patches=[patch], run=_FakeRun())

    result = await reconcile_patches(
        client, "o/r", 1, "sha123", "reopened", session
    )

    assert len(result) == 1
    assert len(client.updated_comments) == 1
    comment_id, body = client.updated_comments[0]
    assert comment_id == 77
    assert "Superseded by v2" in body


# -- closed action --

@pytest.mark.asyncio
async def test_reconcile_close_marks_offered_rejected():
    patch = _FakePatch(status="offered")
    client = _FakeClient()
    session = _FakeSession(patches=[patch], run=_FakeRun())

    result = await reconcile_patches(
        client, "o/r", 1, "sha123", "closed", session
    )

    assert result == []
    assert patch.status == "rejected"
    assert session.committed


# -- no run found --

@pytest.mark.asyncio
async def test_reconcile_returns_empty_when_no_run():
    client = _FakeClient()
    session = _FakeSession(patches=[], run=None)

    result = await reconcile_patches(
        client, "o/r", 1, "sha123", "synchronize", session
    )

    assert result == []


# -- no offered patches --

@pytest.mark.asyncio
async def test_reconcile_returns_empty_when_no_offered_patches():
    client = _FakeClient()
    session = _FakeSession(patches=[], run=_FakeRun())

    result = await reconcile_patches(
        client, "o/r", 1, "sha123", "synchronize", session
    )

    assert result == []
