from critiq.core.findings import Finding
from critiq.core.policy import Category, ReviewPolicy, Severity


def _finding(severity: Severity, confidence: float) -> Finding:
    return Finding(
        category=Category.SECURITY,
        file_path="app/x.py",
        title="t",
        explanation="e",
        evidence="v",
        recommendation="r",
        severity=severity,
        confidence=confidence,
    )


def test_policy_blocks_low_severity():
    policy = ReviewPolicy.defaults()  # medium threshold, 0.85 confidence
    assert _finding(Severity.LOW, 0.95).passes_policy(policy) is False
    assert _finding(Severity.HIGH, 0.95).passes_policy(policy) is True


def test_policy_blocks_low_confidence_default():
    policy = ReviewPolicy.defaults()
    assert _finding(Severity.HIGH, 0.5).passes_policy(policy) is False


def test_policy_disabled_category_blocks():
    policy = ReviewPolicy({"review": {"categories": {"security": False}}})
    assert _finding(Severity.HIGH, 0.99).passes_policy(policy) is False
