from __future__ import annotations

from pathlib import Path

from critiq.ai.providers.base import LLMProvider
from critiq.ai.reviewers.base import LlmReviewer
from critiq.core.policy import Category, ReviewPolicy

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_CATEGORY_PROMPTS: dict[Category, str] = {
    Category.CORRECTNESS: "correctness.txt",
    Category.SECURITY: "security.txt",
    Category.ARCHITECTURE: "architecture.txt",
    Category.RELIABILITY: "reliability.txt",
    Category.PERFORMANCE: "performance.txt",
    Category.TESTING: "testing.txt",
}

_ALL_CATEGORIES = list(Category)


def _read_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()


def build_reviewers(
    provider: LLMProvider,
    policy: ReviewPolicy,
    model: str | None = None,
) -> list[LlmReviewer]:
    """Build LLM reviewers for the categories enabled by the policy."""
    reviewers: list[LlmReviewer] = []
    for category in _ALL_CATEGORIES:
        if not policy.allows_category(category):
            continue
        prompt_file = _CATEGORY_PROMPTS[category]
        reviewers.append(
            LlmReviewer(
                category=category,
                provider=provider,
                system_prompt=_read_prompt(prompt_file),
                model=model or "",
            )
        )
    return reviewers


def read_synthesis_prompt() -> str:
    return _read_prompt("synthesize.txt")
