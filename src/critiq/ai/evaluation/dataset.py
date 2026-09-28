from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from critiq.ai.history import HistoryBlock, HistoryStatus, PathHistory
from critiq.core.policy import Category, Severity

ALLOWED_STATUS_OVERRIDES = (HistoryStatus.UNAVAILABLE, HistoryStatus.NOT_EXPLORED)


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
class EvalHistory:
    """Recorded history for one changed file, authored in the dataset (AC-3).

    The status is derived from the lines rather than authored, so a case cannot
    declare a file clean while listing lines for it. Only the two failure
    wordings need an override, because those say something the lines cannot.
    """

    commits: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    status_override: HistoryStatus | None = None

    @property
    def status(self) -> HistoryStatus:
        if self.status_override is not None:
            return self.status_override
        if self.commits or self.findings:
            return HistoryStatus.OK
        return HistoryStatus.EMPTY

    @property
    def detail_line_count(self) -> int:
        return len(self.commits) + len(self.findings)

    def to_path_history(self, path: str) -> PathHistory:
        return PathHistory(
            path=path,
            status=self.status,
            commit_lines=self.commits,
            finding_lines=self.findings,
        )

    @classmethod
    def from_dict(cls, data: dict) -> EvalHistory:
        raw = data.get("status")
        override: HistoryStatus | None = None
        if raw is not None:
            allowed = {s.value for s in ALLOWED_STATUS_OVERRIDES}
            if raw not in allowed:
                raise ValueError(
                    f"history status must be one of {', '.join(sorted(allowed))}, got {raw!r}. "
                    "ok and empty are derived from the lines, not authored."
                )
            override = HistoryStatus(raw)
        return cls(
            commits=tuple(str(line) for line in data.get("commits", ())),
            findings=tuple(str(line) for line in data.get("findings", ())),
            status_override=override,
        )


@dataclass(slots=True)
class EvalFile:
    path: str
    patch: str
    source: str
    history: EvalHistory | None = None

    @property
    def history_lines_authored(self) -> int:
        return self.history.detail_line_count if self.history else 0


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
                history=EvalHistory.from_dict(f["history"]) if f.get("history") else None,
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


def history_for_case(case: EvalCase) -> HistoryBlock:
    """Fold a case's changed files into one block, one entry per file (AC-1).

    A file with no authored block becomes a confirmed empty record rather than an
    absent one, so the prompt tells the model the file was checked and found
    clean instead of leaving it unclear.
    """
    return HistoryBlock(
        entries={
            f.path: (f.history or EvalHistory()).to_path_history(f.path) for f in case.files
        },
        changed_file_count=len(case.files),
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
