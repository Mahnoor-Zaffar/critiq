from __future__ import annotations

import json
from typing import Any

import httpx

from critiq.core.config import settings


class NoAPIKeyError(RuntimeError):
    pass


class OpenRouterProvider:
    """OpenRouter chat-completions provider (OpenAI-compatible)."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or settings.openrouter_api_key

    @property
    def base_url(self) -> str:
        return settings.openrouter_base_url.rstrip("/")

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise NoAPIKeyError("OpenRouter API key not configured")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "critiq_output",
                    "strict": True,
                    "schema": schema,
                },
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            body = resp.json()

        content = body["choices"][0]["message"]["content"]
        return self._parse_content(content, schema)

    @staticmethod
    def _parse_content(content: str, schema: dict[str, Any] | None) -> dict[str, Any]:
        if schema:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return _extract_json(content)
        return {"text": content}


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from a model response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {"text": text}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"text": text}
