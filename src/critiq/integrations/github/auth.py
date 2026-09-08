from __future__ import annotations

import time
from pathlib import Path

import httpx
import jwt

from critiq.core.config import settings

_GITHUB_API = "https://api.github.com"


class GitHubAuthError(RuntimeError):
    pass


class GitHubAuth:
    """Handles GitHub App JWT and installation access tokens."""

    def __init__(self, app_id: str, private_key: str) -> None:
        if not app_id or not private_key:
            raise GitHubAuthError("Missing GitHub App ID or private key")
        self.app_id = app_id
        self.private_key = private_key

    def make_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now, "exp": now + 600, "iss": self.app_id}
        key = self.private_key
        if "\n" not in key:
            try:
                key = Path(key).read_text()
            except Exception as exc:
                raise GitHubAuthError(f"Could not read private key: {exc}") from exc
        return jwt.encode(payload, key, algorithm="RS256")

    async def get_installation_token(self, installation_id: int) -> str:
        """Exchange an App JWT for a short-lived installation access token."""
        jwt_value = self.make_jwt()
        url = f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_value}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            return resp.json()["token"]


def default_auth() -> GitHubAuth:
    return GitHubAuth(settings.github_app_id, settings.github_app_private_key)
