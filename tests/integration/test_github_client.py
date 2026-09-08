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
