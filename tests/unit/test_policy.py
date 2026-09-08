from critiq.core.policy import Category, ReviewPolicy, Severity


def test_defaults():
    p = ReviewPolicy.defaults()
    assert p.mode == "automatic"
    assert p.severity_threshold == Severity.MEDIUM
    assert p.confidence_threshold == 0.85
    assert p.allows_category(Category.SECURITY)
    assert p.languages == {"python"}


def test_disable_category_and_mode():
    p = ReviewPolicy(
        {
            "review": {
                "mode": "approval",
                "categories": {
                    "security": False,
                    "correctness": True,
                    "architecture": True,
                    "reliability": True,
                    "performance": True,
                    "testing": True,
                },
                "confidence_threshold": 0.9,
            }
        }
    )
    assert p.mode == "approval"
    assert not p.allows_category(Category.SECURITY)
    assert p.allows_category(Category.CORRECTNESS)
    assert p.confidence_threshold == 0.9


def test_from_file_missing_returns_defaults(tmp_path):
    policy = ReviewPolicy.from_file(tmp_path / ".critiq.yml")
    assert policy.mode == "automatic"
