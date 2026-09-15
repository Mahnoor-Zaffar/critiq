from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatch

from critiq.analysis.context import RepoContext
from critiq.analysis.diff import FileDiff
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, CustomRule


class CustomRuleEngine:
    """Deterministic checks for user-defined rules (see `review.rules`).

    Matches each rule's compiled patterns against the diff's added lines only,
    so findings are always tied to lines the PR actually introduces.
    """

    def __init__(self, rules: Iterable[CustomRule]) -> None:
        self.rules = list(rules)

    def analyze(self, context: RepoContext, diff: FileDiff) -> list[Finding]:
        if not self.rules:
            return []
        source = context.modules.get(diff.path)
        text = source.source if source else context.related_files.get(diff.path, "")
        added = set(diff.added_lines)

        findings: list[Finding] = []
        for rule in self.rules:
            if not rule.patterns or not fnmatch(diff.path, rule.path):
                continue
            category = next(iter(rule.categories), Category.CORRECTNESS)
            for line_no, line in enumerate(text.splitlines(), start=1):
                if line_no not in added:
                    continue
                if any(pattern.search(line) for pattern in rule.patterns):
                    findings.append(
                        self._finding(rule, category, diff.path, line_no, line)
                    )
        return findings

    @staticmethod
    def _finding(
        rule: CustomRule, category: Category, file_path: str, line_no: int, line: str
    ) -> Finding:
        return Finding(
            category=category,
            file_path=file_path,
            line_start=line_no,
            line_end=line_no,
            severity=rule.severity,
            confidence=0.95,
            title=rule.name,
            explanation=rule.description,
            evidence=f"`{line.strip()[:80]}` on line {line_no}.",
            recommendation=f"Resolve the violation of rule '{rule.name}' before merging.",
            source=FindingSource.STATIC,
        )
