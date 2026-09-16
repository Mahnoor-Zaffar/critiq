from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("critiq.autofix.workspace")


@dataclass(slots=True)
class Workspace:
    """A checked-out pull request head ready for patch apply + tests."""

    root: Path

    def apply_patch(
        self, relative_path: str, line_start: int, line_end: int, replacement: str
    ) -> None:
        path = self.root / relative_path
        lines = path.read_text(encoding="utf-8").splitlines()
        head = lines[: line_start - 1]
        tail = lines[line_end:]
        text = "\n".join([*head, replacement, *tail])
        path.write_text(text + "\n", encoding="utf-8")


class WorkspaceManager:
    """Shallow base-SHA cached checkouts of a pull request head ref.

    A base clone is cached per base SHA and reused across events; each checkout
    then fetches `refs/pull/{number}/head` into it so fork PRs resolve.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        if base_dir:
            self.base_dir = Path(base_dir)
            self.base_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.base_dir = Path(tempfile.mkdtemp(prefix="critiq-ws-"))

    def base_cache_path(self, base_sha: str) -> Path:
        return self.base_dir / f"base-{base_sha}"

    async def checkout(
        self, clone_url: str, number: int, head_ref: str, base_sha: str
    ) -> Workspace:
        base = self.base_cache_path(base_sha)
        if not (base / ".git").exists():
            await self._run(
                ["git", "clone", "--filter=blob:none", "--no-checkout", clone_url, str(base)]
            )
        await self._run(["git", "fetch", "-q", "origin", f"refs/pull/{number}/head"], cwd=base)
        await self._run(["git", "reset", "-q", "--hard", "FETCH_HEAD"], cwd=base)
        return Workspace(base)

    @staticmethod
    async def _run(args: list[str], cwd: Path | None = None) -> None:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"{args[0]} {' '.join(args[1:])} -> {proc.returncode}: "
                f"{stderr.decode('utf-8', 'replace')[:400]}"
            )
