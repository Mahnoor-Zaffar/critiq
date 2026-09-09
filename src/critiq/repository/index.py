from __future__ import annotations

from dataclasses import dataclass, field

from critiq.analysis.ast import ModuleInfo, Symbol
from critiq.analysis.graph import ImportGraph


@dataclass(slots=True)
class RepoIndex:
    """A persistent, reusable index of a repository checkout.

    Built once, reused across reviews for fast context retrieval instead of
    re-parsing the whole repository on every PR.
    """

    root: str
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    graph: ImportGraph = field(default_factory=ImportGraph)

    @property
    def file_count(self) -> int:
        return len(self.modules)

    @property
    def total_lines(self) -> int:
        return sum(m.source.count("\n") for m in self.modules.values())

    def symbols_for(self, path: str, kind: str | None = None) -> list:
        info = self.modules.get(path)
        if info is None:
            return []
        if kind is None:
            return info.symbols
        return [s for s in info.symbols if s.kind == kind]

    def related_for_change(self, path: str, depth: int = 1) -> list[str]:
        return sorted(self.graph.related_paths(path, depth=depth))

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "modules": {
                path: {
                    "imports": info.imports,
                    "symbols": [
                        {"name": s.name, "kind": s.kind,
                         "start_line": s.start_line, "end_line": s.end_line}
                        for s in info.symbols
                    ],
                    "source": info.source,
                }
                for path, info in self.modules.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> RepoIndex:
        index = cls(root=data.get("root", ""))
        for path, mdata in data.get("modules", {}).items():
            info = ModuleInfo(
                path=path,
                imports=mdata.get("imports", []),
                source=mdata.get("source", ""),
            )
            info.symbols = [
                Symbol(
                    name=s["name"], kind=s["kind"],
                    start_line=s["start_line"], end_line=s["end_line"],
                )
                for s in mdata.get("symbols", [])
            ]
            index.modules[path] = info
            index.graph.add_module(path, info)
        return index
