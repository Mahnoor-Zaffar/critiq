from __future__ import annotations

from typing import Any

from critiq.ai.providers.openrouter import _extract_json


class MockProvider:
    """Deterministic provider used in tests and offline runs.

    Returns a canned response parsed from the given JSON string.
    """

    def __init__(self, response: str = "{}", model: str = "mock") -> None:
        if response.strip().startswith("{"):
            self.response = _extract_json(response)
        else:
            self.response = {"text": response}
        self.model = model

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.response
