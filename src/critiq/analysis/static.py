from __future__ import annotations

import re

from critiq.analysis.context import RepoContext
from critiq.analysis.diff import FileDiff
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, Severity

_SECRET_RE = re.compile(
    r"(api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"]+['\"]",
    re.IGNORECASE,
)
_SHELL_TRUE_RE = re.compile(r"shell\s*=\s*True")
_OS_SYSTEM_RE = re.compile(r"os\.system\(")
_HTTP_WITHOUT_TIMEOUT_RE = re.compile(
    r"(requests\.|httpx\.|async with httpx|client\.(get|post|put|delete|request))\("
)


class StaticAnalyzer:
    """Deterministic pattern checks that run without an LLM."""

    def analyze(self, context: RepoContext, diff: FileDiff) -> list[Finding]:
        findings: list[Finding] = []
        source = context.modules.get(diff.path)
        # Prefer source from related_files if the module wasn't parsed.
        text = source.source if source else context.related_files.get(diff.path, "")

        for line_no, line in enumerate(
            text.splitlines(), start=1
        ):
            if line_no not in set(diff.added_lines):
                continue
            if _SECRET_RE.search(line):
                findings.append(
                    Finding(
                        category=Category.SECURITY,
                        file_path=diff.path,
                        line_start=line_no,
                        line_end=line_no,
                        severity=Severity.HIGH,
                        confidence=0.97,
                        title="Hardcoded secret or credential",
                        explanation="A secret-like value appears to be hardcoded in source.",
                        evidence=f"`{line.strip()[:80]}` on line {line_no}.",
                        recommendation=(
                            "Move secrets to environment variables or a secrets manager."
                        ),
                        source=FindingSource.STATIC,
                    )
                )
            if _OS_SYSTEM_RE.search(line):
                findings.append(
                    Finding(
                        category=Category.SECURITY,
                        file_path=diff.path,
                        line_start=line_no,
                        line_end=line_no,
                        severity=Severity.HIGH,
                        confidence=0.9,
                        title="os.system command invocation",
                        explanation=(
                            "`os.system` runs a shell command and is a common "
                            "command-injection vector."
                        ),
                        evidence=f"`{line.strip()[:80]}` on line {line_no}.",
                        recommendation=(
                            "Use `subprocess.run([...], shell=False)` with a list "
                            "of arguments."
                        ),
                        source=FindingSource.STATIC,
                    )
                )
            if _SHELL_TRUE_RE.search(line):
                findings.append(
                    Finding(
                        category=Category.SECURITY,
                        file_path=diff.path,
                        line_start=line_no,
                        line_end=line_no,
                        severity=Severity.CRITICAL,
                        confidence=0.98,
                        title="Shell execution with shell=True",
                        explanation=(
                            "Using `shell=True` with untrusted input risks command "
                            "injection."
                        ),
                        evidence=f"`{line.strip()[:80]}` on line {line_no}.",
                        recommendation="Avoid `shell=True`; pass args as a list.",
                        source=FindingSource.STATIC,
                    )
                )
        return findings
