from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from critiq.analysis.ast import ModuleInfo, PythonParser
from critiq.analysis.diff import FileDiff
from critiq.analysis.graph import ImportGraph

FileFetcher = Callable[[str], Awaitable[str | None]]


@dataclass(slots=True)
class RepoContext:
    """Relevant repository context assembled for the LLM."""

    changed_files: list[FileDiff] = field(default_factory=list)
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    related_files: dict[str, str] = field(default_factory=dict)  # path -> source
    policy_yaml: str = ""

    def render(self) -> str:
        """Render a compact textual context for the LLM."""
        chunks: list[str] = []

        if self.policy_yaml:
            chunks.append("## Review policy (.critiq.yml)\n```yaml\n" + self.policy_yaml + "\n```")

        chunks.append("## Changed files")
        for fd in self.changed_files:
            added = ", ".join(str(x) for x in fd.added_lines[:60]) or "none"
            chunks.append(f"- {fd.path}: added lines [{added}]")

        if self.related_files:
            chunks.append("\n## Related source (imports/dependents)")
            for path, source in self.related_files.items():
                chunks.append(f"\n### {path}\n```python\n{source[:4000]}\n```")

        return "\n".join(chunks)


class ContextBuilder:
    def __init__(self, parser: PythonParser | None = None) -> None:
        self.parser = parser or PythonParser()

    async def build(
        self,
        changed_files: list[FileDiff],
        fetch: FileFetcher,
        policy_yaml: str = "",
        related_limit: int = 8,
        repo_index=None,
    ) -> RepoContext:
        context = RepoContext(changed_files=changed_files, policy_yaml=policy_yaml)
        graph = ImportGraph()

        for fd in changed_files:
            if repo_index is not None and fd.path in repo_index.modules:
                info = repo_index.modules[fd.path]
            else:
                source = await fetch(fd.path)
                if not source:
                    continue
                info = self.parser.parse_module(fd.path, source)
            context.modules[fd.path] = info
            graph.add_module(fd.path, info)

        related: set[str] = set()
        for path in list(context.modules):
            if repo_index is not None:
                related.update(repo_index.related_for_change(path))
            else:
                related.update(graph.related_paths(path))

        for path in related:
            if path in context.modules or path in context.related_files:
                continue
            if len(context.related_files) >= related_limit:
                break
            if repo_index is not None and path in repo_index.modules:
                context.related_files[path] = repo_index.modules[path].source
                continue
            source = await fetch(path)
            if source:
                context.related_files[path] = source

        return context
