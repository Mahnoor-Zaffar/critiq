from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from critiq.core.config import settings

logger = logging.getLogger("critiq.autofix.tests")

PASSED = "passed"
FAILED = "failed"
UNVERIFIED = "unverified"

_NO_TESTS_COLLECTED = "no tests collected"


@dataclass(slots=True, frozen=True)
class PatchStatus:
    status: str  # passed | failed | unverified
    detail: str = ""


def is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def discover_target_tests(root: Path, changed_path: str) -> list[Path]:
    """Map a changed file to its targeted test candidates (spec heuristic).

    A test file runs itself; otherwise look for `test_<stem>.py` next to the
    file and under `tests/`.
    """
    changed = Path(changed_path)
    if changed.suffix != ".py":
        return []
    if is_test_file(changed):
        candidate = root / changed
        return [candidate] if candidate.exists() else []
    candidates: list[Path] = []
    sibling = root / changed.parent / f"test_{changed.stem}.py"
    if sibling.exists():
        candidates.append(sibling)
    mirrored = root / "tests" / changed.parent / f"test_{changed.stem}.py"
    if mirrored.exists() and mirrored != sibling:
        candidates.append(mirrored)
    return candidates


class PatchVerifier:
    """Runs an eligible patch's targeted tests in an isolated subprocess.

    Apply-then-run happens against a prepared workspace root via the injected
    `workspaces` factory. Dependency injection keeps the verdict semantics
    unit-testable while the worker wires the real git checkout.
    """

    def __init__(
        self,
        workspaces=None,
        runner=None,
        timeout: float | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.runner = runner or run_targeted_tests
        self.timeout = timeout if timeout is not None else settings.test_timeout_seconds

    async def verify(
        self,
        relative_path: str,
        line_start: int,
        line_end: int,
        replacement: str,
    ) -> PatchStatus:
        if self.workspaces is None:
            return PatchStatus(UNVERIFIED, "no workspace configured")
        workspace = await self.workspaces.checkout()
        workspace.apply_patch(relative_path, line_start, line_end, replacement)
        return await self.runner(workspace.root, relative_path, self.timeout)


async def run_targeted_tests(
    root: Path, changed_path: str, timeout: float
) -> PatchStatus:
    """Run `uv sync` then the changed file's targeted pytest, capped at
    `timeout` with a process group kill. Exit semantics per the spec."""
    changed = Path(changed_path)
    if changed.suffix != ".py":
        return PatchStatus(UNVERIFIED, "non-Python file")
    candidates = discover_target_tests(root, changed_path)
    if not candidates:
        return PatchStatus(UNVERIFIED, "no matching test file")

    env = _stripped_env()
    if not await _provision(root, env):
        return PatchStatus(UNVERIFIED, "dependency provisioning failed")

    for candidate in candidates:
        verdict = await _run_pytest(root, candidate, env, timeout)
        if verdict.status != UNVERIFIED:
            return verdict
    return PatchStatus(UNVERIFIED, "no tests collected")


async def _provision(root: Path, env: dict[str, str]) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "uv", "sync", cwd=str(root), env=env,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=300)
    except TimeoutError:
        _kill_process_group(proc)
        return False
    return proc.returncode == 0


async def _run_pytest(
    root: Path, candidate: Path, env: dict[str, str], timeout: float
) -> PatchStatus:
    if candidate.is_absolute():
        rel = candidate.relative_to(root).as_posix()
    else:
        rel = candidate.as_posix()
    try:
        proc = await asyncio.create_subprocess_exec(
            "uv", "run", "pytest", "-q", rel, cwd=str(root), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not launch pytest: %s", exc)
        return PatchStatus(UNVERIFIED, f"could not launch pytest: {exc}")
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        _kill_process_group(proc)
        await proc.wait()
        return PatchStatus(UNVERIFIED, "test timeout")
    output = stdout.decode("utf-8", "replace")
    if proc.returncode == 0:
        return PatchStatus(PASSED, f"targeted tests passed ({candidate.name})")
    if _NO_TESTS_COLLECTED in output.lower():
        return PatchStatus(UNVERIFIED, f"no tests collected ({candidate.name})")
    return PatchStatus(FAILED, output[-2000:].strip())


def _stripped_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("CRITIQ_ADMIN_TOKEN", None)
    return env


def _kill_process_group(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
