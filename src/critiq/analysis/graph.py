from __future__ import annotations

from dataclasses import dataclass, field

from critiq.analysis.ast import ModuleInfo


@dataclass(slots=True)
class ImportGraph:
    """Lightweight module import graph built from parsed modules."""

    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    imports: dict[str, list[str]] = field(default_factory=dict)
    reverse: dict[str, list[str]] = field(default_factory=dict)  # module -> importers

    def add_module(self, path: str, info: ModuleInfo) -> None:
        self.modules[path] = info
        self.imports[path] = info.imports
        for imp in info.imports:
            self.reverse.setdefault(imp, []).append(path)

    def related_paths(self, path: str, depth: int = 1) -> set[str]:
        """Return paths related to `path` by imports, up to `depth` hops."""
        related: set[str] = set()
        frontier = [path]
        for _ in range(depth):
            next_frontier: list[str] = []
            for current in frontier:
                for target in self._direct_targets(current):
                    if target in self.modules and target not in related:
                        related.add(target)
                        next_frontier.append(target)
            frontier = next_frontier
        return related

    def _direct_targets(self, path: str) -> list[str]:
        targets: list[str] = []
        for imp in self.imports.get(path, []):
            for candidate in self.modules:
                if _module_matches(imp, candidate):
                    targets.append(candidate)
        targets.extend(self.reverse.get(path, []))
        return targets


def _module_matches(import_stmt: str, module_path: str) -> bool:
    """Roughly match an import statement to a module path.

    e.g. `from services import evaluation` matches `services/evaluation.py`.
    """
    mod = module_path.replace("/", ".").replace(".py", "")
    if import_stmt.strip().startswith("import "):
        target = import_stmt.strip()[len("import ") :].strip()
        if target == mod or mod.startswith(target + "."):
            return True
    if import_stmt.strip().startswith("from "):
        target = import_stmt.strip()[len("from ") :].split(" import ")[0].strip()
        if target == mod or mod.startswith(target + "."):
            return True
        # e.g. from services.evaluation import X
        if target in mod:
            return True
    return False
