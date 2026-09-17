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

    async def get_file_sha(self, repo: str, path: str, ref: str) -> str | None:
        resp = await self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
        )
        data = resp.json()
        if data.get("type") == "file":
            return data.get("sha")
        return None

    async def get_recent_commits(
        self, repo: str, sha: str, path: str, per_page: int = 3
    ) -> list[dict]:
        """Commits that touched ``path``, reachable from ``sha`` (base ref)."""
        resp = await self._request(
            "GET",
            f"/repos/{repo}/commits",
            params={"sha": sha, "path": path, "per_page": per_page},
        )
        return [
            {
                "sha": commit.get("sha", ""),
                "message": (commit.get("commit") or {})
                .get("message", "")
                .splitlines()[0],
            }
            for commit in resp.json()
        ]

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

    async def update_review_comment(
        self, repo: str, comment_id: int, body: str
    ) -> dict:
        resp = await self._request(
            "PATCH",
            f"/repos/{repo}/pulls/comments/{comment_id}",
            json={"body": body},
        )
        return resp.json()

    async def get_review_comment(self, repo: str, comment_id: int) -> str:
        resp = await self._request(
            "GET", f"/repos/{repo}/pulls/comments/{comment_id}"
        )
        return resp.json().get("body", "")

    async def get_ref(self, repo: str, ref: str) -> str | None:
        resp = await self._request(
            "GET", f"/repos/{repo}/git/ref/heads/{ref}"
        )
        return resp.json().get("object", {}).get("sha")

    async def update_file_content(
        self,
        repo: str,
        path: str,
        message: str,
        content: str,
        current_sha: str,
        branch: str,
    ) -> dict:
        import base64

        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": message,
            "content": encoded,
            "sha": current_sha,
            "branch": branch,
        }
        resp = await self._request(
            "PUT", f"/repos/{repo}/contents/{path}", json=payload
        )
        return resp.json()

    async def branch_protected(self, repo: str, branch: str) -> bool:
        try:
            await self._request(
                "GET", f"/repos/{repo}/branches/{branch}/protection"
            )
            return True
        except GitHubClientError:
            return False

    async def patch_diff_basis(self, repo: str, number: int, path: str, line: int) -> bool:
        """True when the added line anchoring a finding is still in the PR diff."""
        files = await self.get_pull_files(repo, number)
        for f in files:
            if f.filename != path or not f.patch:
                continue
            added = [
                int(ln)
                for ln in _added_line_numbers(f.patch)
            ]
            return line in added
        return False


def _added_line_numbers(patch: str) -> list[int]:
    lines = []
    new_line = 0
    for raw in patch.splitlines():
        if raw.startswith("@@ "):
            parts = raw.split("+")[1].split(" ")[0]
            new_line = int(parts.split(",")[0])
            continue
        if raw.startswith("+"):
            lines.append(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            new_line += 1
    return lines


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
