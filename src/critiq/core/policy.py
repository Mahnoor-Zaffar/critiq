from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("critiq.policy")


class ReviewMode(StrEnum):
    AUTOMATIC = "automatic"
    APPROVAL = "approval"
    ADVISORY = "advisory"


class Category(StrEnum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    RELIABILITY = "reliability"
    PERFORMANCE = "performance"
    TESTING = "testing"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class CustomRule:
    """A user-defined engineering rule enforced by Critiq.

    `patterns` are compiled regexes matched against added lines by the static
    engine; `description` is also injected into LLM reviewer prompts so
    semantic violations can be caught with evidence.
    """

    id: str
    name: str
    description: str
    severity: Severity
    categories: frozenset[Category]
    path: str
    patterns: tuple[re.Pattern[str], ...]

    def applies_to(self, category: Category | None) -> bool:
        return not self.categories or category in self.categories


class ReviewPolicy:
    """Parsed `.critiq.yml` review behavior for a repository."""

    DEFAULT_CATEGORIES = frozenset(cat for cat in Category)
    DEFAULT_MODE = ReviewMode.AUTOMATIC
    DEFAULT_SEVERITY_THRESHOLD = Severity.MEDIUM
    DEFAULT_CONFIDENCE_THRESHOLD = 0.85
    DEFAULT_MAX_COMMENTS = 10
    DEFAULT_FIX_ENABLED = False
    DEFAULT_FIX_CATEGORIES = frozenset({Category.SECURITY, Category.CORRECTNESS})
    DEFAULT_MAX_PATCHES = 10
    DEFAULT_FIX_APPLY = "suggest"

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        review = data.get("review", {}) or {}

        mode = review.get("mode", self.DEFAULT_MODE)
        self.mode = ReviewMode(mode) if isinstance(mode, str) else self.DEFAULT_MODE

        severity = review.get(
            "severity_threshold", self.DEFAULT_SEVERITY_THRESHOLD
        )
        self.severity_threshold = (
            Severity(severity) if isinstance(severity, str) else self.DEFAULT_SEVERITY_THRESHOLD
        )

        self.confidence_threshold = float(
            review.get("confidence_threshold", self.DEFAULT_CONFIDENCE_THRESHOLD)
        )
        self.max_comments = int(review.get("max_comments", self.DEFAULT_MAX_COMMENTS))

        categories = review.get("categories", {}) or {}
        if categories:
            self.enabled_categories = frozenset(
                cat for cat, enabled in categories.items() if enabled and cat in Category
            )
        else:
            self.enabled_categories = self.DEFAULT_CATEGORIES

        routing = review.get("model_routing", {}) or {}
        self.cheap_model = routing.get("cheap") or ""
        self.strong_model = routing.get("strong") or ""

        languages = review.get("languages", ["python"]) or ["python"]
        self.languages = frozenset(languages)

        self.profile = review.get("profile") or ""
        self.rules = self._parse_rules(review.get("rules"))

        fix = review.get("fix", {}) or {}
        self.fix_enabled = bool(fix.get("enabled", self.DEFAULT_FIX_ENABLED))
        raw_categories = fix.get("categories") or []
        explicit = frozenset(
            Category(c) for c in raw_categories if isinstance(c, str) and c in Category
        )
        self.fix_categories = explicit or self.DEFAULT_FIX_CATEGORIES
        max_patches = fix.get("max_patches", self.DEFAULT_MAX_PATCHES)
        try:
            self.max_patches = int(max_patches)
        except (TypeError, ValueError):
            self.max_patches = self.DEFAULT_MAX_PATCHES
        fix_apply = fix.get("apply", self.DEFAULT_FIX_APPLY)
        self.fix_apply = fix_apply if fix_apply in ("suggest", "push") else self.DEFAULT_FIX_APPLY

    @classmethod
    def defaults(cls) -> ReviewPolicy:
        return cls()

    @classmethod
    def from_file(cls, path: Path) -> ReviewPolicy:
        if not path.exists():
            return cls.defaults()
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data)

    def allows_category(self, category: Category) -> bool:
        return category in self.enabled_categories

    def passes_confidence(self, score: float) -> bool:
        return score >= self.confidence_threshold

    def rule_text(self, category: Category | None = None) -> str:
        """Natural-language rules block for LLM reviewer prompts."""
        applicable = [
            r for r in self.rules if category is None or r.applies_to(category)
        ]
        if not applicable:
            return ""
        lines = ["Custom engineering rules this repository enforces:"]
        for rule in applicable:
            lines.append(f"- {rule.name}: {rule.description}")
        return "\n".join(lines)

    @staticmethod
    def _parse_rules(raw) -> list[CustomRule]:
        if not isinstance(raw, list):
            return []
        rules: list[CustomRule] = []
        for entry in raw:
            if not isinstance(entry, dict):
                logger.warning("skipping invalid custom rule entry %r", entry)
                continue
            rule = _parse_rule(entry)
            if rule is not None:
                rules.append(rule)
        return rules


def _parse_rule(entry: dict[str, Any]) -> CustomRule | None:
    rule_id = entry.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        logger.warning("skipping custom rule without an `id` string")
        return None

    description = entry.get("description")
    if not isinstance(description, str):
        logger.warning("custom rule %r has no `description`; skipping", rule_id)
        return None

    severity_raw = entry.get("severity", Severity.MEDIUM)
    if not isinstance(severity_raw, str) or severity_raw not in Severity:
        logger.warning("custom rule %r has invalid severity %r; skipping", rule_id, severity_raw)
        return None

    category_raw = entry.get("categories") or []
    categories = frozenset(
        Category(c) for c in category_raw if isinstance(c, str) and c in Category
    )

    patterns_raw = entry.get("patterns") or []
    patterns: tuple[re.Pattern[str], ...] = ()
    for pattern in patterns_raw:
        if not isinstance(pattern, str):
            logger.warning("custom rule %r has a non-string pattern; skipping", rule_id)
            return None
        try:
            patterns = (*patterns, re.compile(pattern))
        except re.error:
            logger.warning("custom rule %r has invalid regex %r; skipping", rule_id, pattern)
            return None

    return CustomRule(
        id=rule_id,
        name=str(entry.get("name", rule_id)),
        description=description,
        severity=Severity(severity_raw),
        categories=categories,
        path=str(entry.get("path", "**/*")),
        patterns=patterns,
    )
