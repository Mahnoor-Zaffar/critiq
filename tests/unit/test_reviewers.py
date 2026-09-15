from critiq.ai.providers.mock import MockProvider
from critiq.ai.reviewers import build_reviewers
from critiq.core.policy import Category, ReviewPolicy


def test_build_reviewers_injects_custom_rules_into_matching_category():
    policy = ReviewPolicy(
        {
            "review": {
                "rules": [
                    {
                        "id": "rule-a",
                        "name": "A",
                        "description": "only security",
                        "categories": ["security"],
                        "patterns": ["x"],
                    },
                    {"id": "rule-b", "name": "B", "description": "everyone", "patterns": ["y"]},
                ]
            }
        }
    )
    reviewers = build_reviewers(MockProvider(), policy)
    prompts = {r.category: r.system_prompt for r in reviewers}

    assert "only security" in prompts[Category.SECURITY]
    assert "everyone" in prompts[Category.SECURITY]
    assert "only security" not in prompts[Category.TESTING]
    assert "everyone" in prompts[Category.TESTING]


def test_build_reviewers_prompt_unchanged_without_rules():
    reviewers = build_reviewers(MockProvider(), ReviewPolicy.defaults())
    prompt = next(r for r in reviewers if r.category == Category.SECURITY).system_prompt
    assert "Custom engineering rules" not in prompt
