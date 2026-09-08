from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    """Provider-agnostic interface over any chat-completions LLM."""

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
