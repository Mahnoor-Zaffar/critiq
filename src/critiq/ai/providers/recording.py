from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from critiq.ai.providers.base import LLMProvider
from critiq.ai.tokens import estimate_tokens

CHANGED_FILE_MARKER = "Changed file: `"
REVIEWER_HISTORY_MARKER = "Recorded history for the file you are reviewing:"
SYNTHESIS_HISTORY_MARKER = "Recorded history (how these files evolved before this PR):"
HISTORY_MARKERS = (REVIEWER_HISTORY_MARKER, SYNTHESIS_HISTORY_MARKER)
FILE_HEADER_PREFIX = "History Context for "
COUNT_LINE_PREFIX = "Recorded history for "


@dataclass(frozen=True, slots=True)
class PromptRecord:
    """One call the harness made, and what actually reached the prompt.

    ``history_section`` says whether the prompt carried a history block at all,
    which is what separates a block that was trimmed from one that never
    arrived, since both would otherwise show zero rendered lines. Rendered is
    counted out of the recorded prompt, and a reviewer section is never trimmed,
    so authored and rendered are equal there (AC-7).
    """

    system: str
    user: str
    schema: dict[str, Any] | None
    file: str | None
    tokens: int
    history_section: bool
    history_lines_authored: int | None
    history_lines_rendered: int


class RecordingProvider:
    """Wraps any provider and keeps every prompt it forwards (AC-5).

    It passes calls through untouched, so wrapping does not change what the
    inner provider does: the mock still returns its canned answer and a real
    provider still bills the same request.
    """

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self._authored_by_file: Mapping[str, int] | None = None
        self.calls: list[PromptRecord] = []

    def set_authored(self, authored_by_file: Mapping[str, int] | None) -> None:
        """Record how many history lines the case about to run authored, by file."""
        self._authored_by_file = authored_by_file

    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = attributed_file(user)
        self.calls.append(
            PromptRecord(
                system=system,
                user=user,
                schema=schema,
                file=path,
                tokens=estimate_tokens(f"{system}\n{user}"),
                history_section=has_history_section(user),
                history_lines_authored=self._authored_for(path),
                history_lines_rendered=rendered_history_lines(user),
            )
        )
        return await self._inner.generate(system=system, user=user, schema=schema)

    def _authored_for(self, path: str | None) -> int | None:
        if self._authored_by_file is None:
            return None
        if path is None:
            return sum(self._authored_by_file.values())
        return self._authored_by_file.get(path, 0)


def attributed_file(user: str) -> str | None:
    """The file a reviewer prompt judges, or None for the synthesis call (AC-5).

    The reviewer's own marker comes before the shared context, so the first
    match is the file being judged even when the context lists others.
    """
    index = user.find(CHANGED_FILE_MARKER)
    if index == -1:
        return None
    rest = user[index + len(CHANGED_FILE_MARKER) :]
    end = rest.find("`")
    return rest[:end] if end != -1 else None


def has_history_section(user: str) -> bool:
    """Whether the prompt carried a history block at all."""
    return any(marker in user for marker in HISTORY_MARKERS)


def rendered_history_lines(user: str) -> int:
    """Count the history detail lines the render emitted, under its own marker.

    The per file headers and the synthesizer's count line are structure, not
    history, so they are excluded and everything else in the block counts. That
    keeps a casually authored dataset line visible instead of looking trimmed.
    Only the run of lines directly under the marker counts, so the instructions
    that follow the block cannot be mistaken for history.
    """
    for marker in HISTORY_MARKERS:
        index = user.find(marker)
        if index == -1:
            continue
        count = 0
        started = False
        for line in user[index + len(marker) :].splitlines():
            if not line.strip():
                if started:
                    break
                continue
            started = True
            if line.startswith(FILE_HEADER_PREFIX) or line.startswith(COUNT_LINE_PREFIX):
                continue
            count += 1
        return count
    return 0
