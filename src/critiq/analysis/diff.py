from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DiffHunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    added_lines: list[int] = field(default_factory=list)  # new-file line numbers
    removed_lines: list[int] = field(default_factory=list)


@dataclass(slots=True)
class FileDiff:
    path: str
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def added_lines(self) -> list[int]:
        return [line for hunk in self.hunks for line in hunk.added_lines]

    def is_line_added(self, line: int) -> bool:
        return line in self.added_lines


def parse_patch(path: str, patch: str | None) -> FileDiff:
    """Parse a unified diff into a FileDiff with new-file line numbers.

    Handles the `@@ -old +new @@` hunk headers emitted by GitHub patches.
    """
    file_diff = FileDiff(path=path)
    if not patch:
        return file_diff

    new_line = 0
    old_line = 0
    current: DiffHunk | None = None

    for raw in patch.splitlines():
        line = raw
        if line.startswith("@@"):
            sm = _parse_hunk_header(line)
            if sm is None:
                continue
            old_start, old_lines, new_start, new_lines = sm
            old_line = old_start
            new_line = new_start
            current = DiffHunk(old_start, old_lines, new_start, new_lines)
            file_diff.hunks.append(current)
            continue

        if current is None:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            current.added_lines.append(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            current.removed_lines.append(old_line)
            old_line += 1
        elif line.startswith("\\"):
            continue
        else:
            old_line += 1
            new_line += 1

    return file_diff


def _parse_hunk_header(line: str) -> tuple[int, int, int, int] | None:
    # e.g. @@ -12,3 +12,5 @@
    import re

    m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
    if not m:
        return None
    old_start = int(m.group(1))
    old_lines = int(m.group(2) or 1)
    new_start = int(m.group(3))
    new_lines = int(m.group(4) or 1)
    return old_start, old_lines, new_start, new_lines
