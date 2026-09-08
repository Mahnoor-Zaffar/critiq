from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


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


class ReviewPolicy:
    """Parsed `.critiq.yml` review behavior for a repository."""

    DEFAULT_CATEGORIES = frozenset(cat for cat in Category)
    DEFAULT_MODE = ReviewMode.AUTOMATIC
    DEFAULT_SEVERITY_THRESHOLD = Severity.MEDIUM
    DEFAULT_CONFIDENCE_THRESHOLD = 0.85
    DEFAULT_MAX_COMMENTS = 10

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
