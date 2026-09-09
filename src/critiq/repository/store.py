from __future__ import annotations

import json
from pathlib import Path

from critiq.analysis.ast import PythonParser
from critiq.repository.index import RepoIndex

_PY_SUFFIXES = {".py"}
_IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}


def build_index(root: str | Path) -> RepoIndex:
    """Walk a checkout and build a RepoIndex from Python source files."""
    root_path = Path(root)
    parser = PythonParser()
    index = RepoIndex(root=str(root_path))

    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _PY_SUFFIXES:
            continue
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root_path).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        info = parser.parse_module(rel, source)
        index.modules[rel] = info
        index.graph.add_module(rel, info)

    return index


class IndexCache:
    """Persists a RepoIndex to a JSON file for reuse across review runs."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        safe = key.replace("/", "_").replace(".", "_")
        return self.cache_dir / f"{safe}.index.json"

    def load(self, key: str) -> RepoIndex | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as fh:
            return RepoIndex.from_dict(json.load(fh))

    def save(self, key: str, index: RepoIndex) -> Path:
        path = self.path_for(key)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(index.to_dict(), fh)
        return path

    def get_or_build(self, key: str, root: str | Path) -> RepoIndex:
        cached = self.load(key)
        if cached is not None:
            return cached
        index = build_index(root)
        self.save(key, index)
        return index
