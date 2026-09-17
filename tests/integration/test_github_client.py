import httpx
import pytest
import respx
from pytest import fixture

from critiq.core.findings import ReviewComment
from critiq.integrations.github.client import GitHubClient

_API = "https://api.github.com"


@fixture
def client():
    return GitHubClient(token="test-token")


@respx.mock
@pytest.mark.asyncio
async def test_get_pull_request(client):
    respx.get(f"{_API}/repos/o/r/pulls/1").mock(
        return_value=httpx.Response(200, json={"number": 1, "title": "t"})
    )
    pr = await client.get_pull_request("o/r", 1)
    assert pr["number"] == 1


@respx.mock
@pytest.mark.asyncio
async def test_get_pull_files_parses_patch(client):
    respx.get(f"{_API}/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "filename": "app/x.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "patch": "@@ -1 +1,2 @@\n a\n+b\n",
                }
            ],
        )
    )
    files = await client.get_pull_files("o/r", 1)
    assert files[0].filename == "app/x.py"
    assert files[0].patch.startswith("@@")


@respx.mock
@pytest.mark.asyncio
async def test_create_review_posts_comments(client):
    route = respx.post(f"{_API}/repos/o/r/pulls/1/reviews").mock(
        return_value=httpx.Response(200, json={"id": 5})
    )
    result = await client.create_review(
        "o/r",
        1,
        "body",
        [ReviewComment(file_path="app/x.py", body="hi", start_line=2)],
    )
    assert result["id"] == 5
    sent = route.calls.last.request.content
    assert b"app/x.py" in sent


@respx.mock
@pytest.mark.asyncio
async def test_get_ref_returns_head_sha(client):
    respx.get(f"{_API}/repos/o/r/git/ref/heads/feat").mock(
        return_value=httpx.Response(200, json={"object": {"sha": "abc123"}})
    )
    sha = await client.get_ref("o/r", "feat")
    assert sha == "abc123"


@respx.mock
@pytest.mark.asyncio
async def test_get_file_sha(client):
    respx.get(f"{_API}/repos/o/r/contents/app/x.py", params={"ref": "feat"}).mock(
        return_value=httpx.Response(
            200, json={"type": "file", "sha": "blobsha"}
        )
    )
    sha = await client.get_file_sha("o/r", "app/x.py", "feat")
    assert sha == "blobsha"


@respx.mock
@pytest.mark.asyncio
async def test_update_file_content_pushes_base64(client):
    import base64

    route = respx.put(f"{_API}/repos/o/r/contents/app/x.py").mock(
        return_value=httpx.Response(
            200, json={"commit": {"sha": "commitsha"}}
        )
    )
    resp = await client.update_file_content(
        "o/r", "app/x.py", "msg", "hello", "blobsha", "feat"
    )
    assert resp["commit"]["sha"] == "commitsha"
    sent = route.calls.last.request.content
    assert b"msg" in sent
    assert base64.b64encode(b"hello") in sent


@respx.mock
@pytest.mark.asyncio
async def test_update_and_get_review_comment(client):
    import json

    route = respx.patch(f"{_API}/repos/o/r/pulls/comments/9").mock(
        return_value=httpx.Response(200, json={"id": 9})
    )
    await client.update_review_comment("o/r", 9, "new body")
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"body": "new body"}

    respx.get(f"{_API}/repos/o/r/pulls/comments/9").mock(
        return_value=httpx.Response(200, json={"body": "new body"})
    )
    body = await client.get_review_comment("o/r", 9)
    assert body == "new body"


@respx.mock
@pytest.mark.asyncio
async def test_branch_protected_true_and_false(client):
    respx.get(f"{_API}/repos/o/r/branches/feat/protection").mock(
        return_value=httpx.Response(200, json={})
    )
    assert await client.branch_protected("o/r", "feat") is True

    respx.get(f"{_API}/repos/o/r/branches/open/protection").mock(
        return_value=httpx.Response(404, json={"message": "nope"})
    )
    assert await client.branch_protected("o/r", "open") is False


@respx.mock
@pytest.mark.asyncio
async def test_patch_diff_basis_line_still_present(client):
    patch = "@@ -1 +1,2 @@\n a\n+b\n"
    respx.get(f"{_API}/repos/o/r/pulls/1/files").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "filename": "app/x.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "patch": patch,
                }
            ],
        )
    )
    assert await client.patch_diff_basis("o/r", 1, "app/x.py", 2) is True
    assert await client.patch_diff_basis("o/r", 1, "app/x.py", 9) is False
    assert await client.patch_diff_basis("o/r", 1, "app/y.py", 2) is False
