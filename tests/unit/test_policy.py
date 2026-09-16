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


def test_custom_rules_parse_valid_entries():
    p = ReviewPolicy(
        {
            "review": {
                "rules": [
                    {
                        "id": "no-hardcoded-secrets",
                        "name": "No credentials in source",
                        "description": "Secrets must come from env vars.",
                        "severity": "high",
                        "categories": ["security", "reliability"],
                        "path": "**/*.py",
                        "patterns": [r'API_(KEY|SECRET)\s*=\s*["\'][^"\']+["\']'],
                    }
                ]
            }
        }
    )
    assert len(p.rules) == 1
    rule = p.rules[0]
    assert rule.id == "no-hardcoded-secrets"
    assert rule.severity == Severity.HIGH
    assert rule.categories == frozenset({Category.SECURITY, Category.RELIABILITY})
    assert rule.applies_to(Category.SECURITY)
    assert not rule.applies_to(Category.TESTING)
    assert rule.patterns and rule.patterns[0].search('API_KEY = "x"')


def test_custom_rules_skip_invalid_entries():
    p = ReviewPolicy(
        {
            "review": {
                "rules": [
                    {"description": "no id", "patterns": ["x"]},
                    {"id": "no-desc"},
                    {"id": "bad-sev", "description": "d", "severity": "urgent", "patterns": ["x"]},
                    {"id": "bad-regex", "description": "d", "patterns": ["("]},
                    {"id": "ok", "description": "d", "severity": "low", "patterns": ["TMP"]},
                ]
            }
        }
    )
    assert [r.id for r in p.rules] == ["ok"]


def test_fix_defaults_disabled():
    p = ReviewPolicy.defaults()
    assert not p.fix_enabled
    assert p.fix_categories == frozenset({Category.SECURITY, Category.CORRECTNESS})
    assert p.max_patches == 10
    assert p.fix_apply == "suggest"


def test_fix_block_parses():
    p = ReviewPolicy(
        {
            "review": {
                "fix": {
                    "enabled": True,
                    "categories": ["security", "performance"],
                    "max_patches": 3,
                    "apply": "push",
                }
            }
        }
    )
    assert p.fix_enabled
    assert p.fix_categories == frozenset({Category.SECURITY, Category.PERFORMANCE})
    assert p.max_patches == 3
    assert p.fix_apply == "push"


def test_fix_block_ignores_bad_values():
    p = ReviewPolicy(
        {
            "review": {
                "fix": {
                    "enabled": True,
                    "categories": ["not-a-category"],
                    "max_patches": "nope",
                    "apply": "sideways",
                }
            }
        }
    )
    assert p.fix_categories == frozenset({Category.SECURITY, Category.CORRECTNESS})
    assert p.max_patches == 10
    assert p.fix_apply == "suggest"


def test_rule_text_empty_when_no_rules():
    defaults = ReviewPolicy.defaults()
    assert defaults.rule_text() == ""
    assert defaults.rule_text(Category.SECURITY) == ""


def test_rule_text_filters_by_category():
    p = ReviewPolicy(
        {
            "review": {
                "rules": [
                    {
                        "id": "sec",
                        "name": "S",
                        "description": "sec rule",
                        "categories": ["security"],
                        "patterns": ["x"],
                    },
                    {"id": "all", "name": "A", "description": "all rule", "patterns": ["y"]},
                ]
            }
        }
    )
    security_text = p.rule_text(Category.SECURITY)
    assert "sec rule" in security_text
    assert "all rule" in security_text
    testing_text = p.rule_text(Category.TESTING)
    assert "sec rule" not in testing_text
    assert "all rule" in testing_text
