from __future__ import annotations

from typing import Any, Protocol

from critiq.ai.providers.base import LLMProvider
from critiq.ai.schemas import FINDING_SCHEMA
from critiq.analysis.context import RepoContext
from critiq.analysis.diff import FileDiff
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, Severity


class Reviewer(Protocol):
    category: Category

    async def review(self, context: RepoContext, diff: FileDiff) -> list[Finding]: ...


class LlmReviewer:
    """Base reviewer that runs a category prompt and parses findings."""

    def __init__(
        self,
        category: Category,
        provider: LLMProvider,
        system_prompt: str,
        model: str | None = None,
    ) -> None:
        self.category = category
        self.provider = provider
        self.system_prompt = system_prompt
        self.model = model or ""

    async def review(self, context: RepoContext, diff: FileDiff) -> list[Finding]:
        user = self._render_user(context, diff)
        raw = await self.provider.generate(
            system=self.system_prompt,
            user=user,
            schema=FINDING_SCHEMA,
        )
        return self._parse(raw.get("findings", []))

    def _render_user(self, context: RepoContext, diff: FileDiff) -> str:
        added = ", ".join(str(x) for x in diff.added_lines[:100])
        return (
            f"Review the PR diff below for {self.category.value} issues.\n\n"
            f"Changed file: `{diff.path}`\n"
            f"Added (new-file) lines: [{added}]\n\n"
            f"Context:\n{context.render()}\n\n"
            "Only report findings that are evidence-backed and tied to the changed "
            "file/line. Prefer fewer, higher-confidence findings. Return JSON matching "
            "the schema with 'findings'."
        )

    def _parse(self, items: list[dict[str, Any]]) -> list[Finding]:
        findings: list[Finding] = []
        for item in items:
            try:
                findings.append(
                    Finding(
                        category=self.category,
                        file_path=item["file_path"],
                        title=item["title"],
                        explanation=item.get("explanation", ""),
                        evidence=item.get("evidence", ""),
                        recommendation=item.get("recommendation", ""),
                        severity=Severity(item.get("severity", "medium")),
                        confidence=float(item.get("confidence", 0.5)),
                        line_start=item.get("line_start"),
                        line_end=item.get("line_end"),
                        source=FindingSource.LLM,
                    )
                )
            except (KeyError, ValueError):
                continue
        return findings
