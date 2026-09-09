from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from critiq.core.policy import Category, Severity


@dataclass(slots=True)
class EvalFinding:
    """A ground-truth finding expected to be detected by the pipeline."""

    category: Category
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    severity: Severity = Severity.HIGH
    useful: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> EvalFinding:
        return cls(
            category=Category(data["category"]),
            file_path=data["file_path"],
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            severity=Severity(data.get("severity", "high")),
            useful=bool(data.get("useful", True)),
        )


@dataclass(slots=True)
class EvalFile:
    path: str
    patch: str
    source: str


@dataclass(slots=True)
class EvalCase:
    """A labeled pull request: changed files + ground-truth findings."""

    id: str
    repo: str
    number: int
    title: str
    files: list[EvalFile]
    expected: list[EvalFinding]

    @property
    def sources(self) -> dict[str, str]:
        return {f.path: f.source for f in self.files}

    @property
    def patches(self) -> dict[str, str]:
        return {f.path: f.patch for f in self.files}

    @classmethod
    def from_dict(cls, data: dict) -> EvalCase:
        files = [
            EvalFile(
                path=f["path"],
                patch=f.get("patch", ""),
                source=f.get("source", ""),
            )
            for f in data.get("files", [])
        ]
        expected = [EvalFinding.from_dict(e) for e in data.get("expected", [])]
        return cls(
            id=data["id"],
            repo=data.get("repo", "example/repo"),
            number=int(data.get("pr", 0)),
            title=data.get("title", ""),
            files=files,
            expected=expected,
        )


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Load evaluation cases from a directory of YAML files (or a single file)."""
    p = Path(path)
    if p.is_file():
        return _load_file(p)
    cases: list[EvalCase] = []
    for f in sorted(p.glob("*.yml")):
        cases.extend(_load_file(f))
    for f in sorted(p.glob("*.yaml")):
        cases.extend(_load_file(f))
    return cases


def _load_file(path: Path) -> list[EvalCase]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not data:
        return []
    if isinstance(data, list):
        return [EvalCase.from_dict(d) for d in data]
    if "cases" in data:
        return [EvalCase.from_dict(d) for d in data["cases"]]
    return [EvalCase.from_dict(data)]
