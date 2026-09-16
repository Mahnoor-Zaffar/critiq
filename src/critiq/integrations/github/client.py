from __future__ import annotations

from dataclasses import dataclass

import httpx

from critiq.core.findings import ReviewComment

_GITHUB_API = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"


@dataclass(slots=True)
class ChangedFile:
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str | None = None


class GitHubClientError(RuntimeError):
    pass


class GitHubClient:
    """Minimal GitHub REST client for PR review workflows."""

    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self.token = token
        self.timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": _ACCEPT,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{_GITHUB_API}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
            if resp.status_code >= 400:
                raise GitHubClientError(f"{method} {path} -> {resp.status_code}: {resp.text}")
            return resp

    async def get_pull_request(self, repo: str, number: int) -> dict:
        resp = await self._request("GET", f"/repos/{repo}/pulls/{number}")
        return resp.json()

    async def get_pull_files(self, repo: str, number: int) -> list[ChangedFile]:
        resp = await self._request("GET", f"/repos/{repo}/pulls/{number}/files")
        files = [
            ChangedFile(**{k: f.get(k) for k in ChangedFile.__dataclass_fields__})
            for f in resp.json()
        ]
        return files

    async def get_file_content(self, repo: str, path: str, ref: str) -> str | None:
        resp = await self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
        )
        data = resp.json()
        if data.get("type") == "file":
            import base64
            return base64.b64decode(data.get("content", "")).decode("utf-8", "replace")
        return None

    async def get_blob(self, repo: str, sha: str) -> str:
        resp = await self._request(
            "GET", f"/repos/{repo}/git/blobs/{sha}",
            params={"Accept": "application/vnd.github.raw"},
        )
        return resp.text

    async def create_review(
        self,
        repo: str,
        number: int,
        body: str,
        comments: list[ReviewComment],
        event: str = "COMMENT",
    ) -> dict:
        payload = {
            "body": body,
            "event": event,
            "comments": [
                _review_comment_payload(c)
                for c in comments
            ],
        }
        resp = await self._request(
            "POST", f"/repos/{repo}/pulls/{number}/reviews", json=payload
        )
        return resp.json()


def _review_comment_payload(c: ReviewComment) -> dict:
    end_line = c.end_line or c.start_line
    item: dict = {
        "path": c.file_path,
        "line": end_line,
        "side": "RIGHT",
        "body": c.body,
    }
    if c.start_line is not None and c.start_line != end_line:
        item["start_line"] = c.start_line
        item["start_side"] = "RIGHT"
    return item
