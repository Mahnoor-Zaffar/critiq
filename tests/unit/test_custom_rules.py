from critiq.analysis.context import RepoContext
from critiq.analysis.custom_rules import CustomRuleEngine
from critiq.analysis.diff import parse_patch
from critiq.core.findings import FindingSource
from critiq.core.policy import Category, ReviewPolicy, Severity

PATCH = """@@ -1,2 +1,6 @@
 import os
+
+API_KEY = "sk-123"
+
+def run():
+    return "ok"
"""

SOURCE = (
    'import os\n\nAPI_KEY = "sk-123"\n\ndef run():\n    return "ok"\n'
)


def _engine(rules=None):
    policy = ReviewPolicy({"review": {"rules": rules or []}})
    return CustomRuleEngine(policy.rules)


def _context(path):
    diff = parse_patch(path, PATCH)
    context = RepoContext(changed_files=[diff], related_files={path: SOURCE})
    return context, diff


def test_engine_flags_matching_added_line():
    engine = _engine(
        [{"id": "no-keys", "description": "no hardcoded keys", "patterns": [r'API_KEY\s*=']}]
    )
    context, diff = _context("app/x.py")
    findings = engine.analyze(context, diff)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.category == Category.CORRECTNESS
    assert finding.severity == Severity.MEDIUM
    assert finding.confidence == 0.95
    assert finding.line_start == 3
    assert finding.source == FindingSource.STATIC


def test_engine_uses_rule_category_and_severity():
    engine = _engine(
        [
            {
                "id": "no-keys",
                "categories": ["security"],
                "severity": "high",
                "description": "no hardcoded keys",
                "patterns": [r'API_KEY\s*='],
            }
        ]
    )
    context, diff = _context("app/x.py")
    finding = engine.analyze(context, diff)[0]
    assert finding.category == Category.SECURITY
    assert finding.severity == Severity.HIGH


def test_engine_skips_non_matching_files_by_glob():
    engine = _engine(
        [{"id": "py-only", "path": "**/*.py", "description": "py only", "patterns": [r'API_KEY']}]
    )
    path = "web/app.js"
    diff = parse_patch(path, PATCH)
    context = RepoContext(changed_files=[diff], related_files={path: SOURCE})
    assert engine.analyze(context, diff) == []


def test_engine_only_checks_added_lines():
    source = 'SECRET = "x"\n\nAPI_KEY = "sk-123"\n\ndef run():\n    return "ok"\n'
    path = "app/x.py"
    diff = parse_patch(path, PATCH)
    context = RepoContext(changed_files=[diff], related_files={path: source})
    engine = _engine(
        [{"id": "secret", "description": "no secrets", "patterns": [r'SECRET\s*=']}]
    )
    findings = engine.analyze(context, diff)
    assert findings == []
    engine2 = _engine(
        [{"id": "apikey", "description": "no api keys", "patterns": [r'API_KEY\s*=']}]
    )
    assert len(engine2.analyze(context, diff)) == 1


def test_engine_ignores_rules_without_patterns():
    engine = _engine([{"id": "meta", "description": "guidance only"}])
    context, diff = _context("app/x.py")
    assert engine.analyze(context, diff) == []
