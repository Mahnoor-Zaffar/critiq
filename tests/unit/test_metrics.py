from critiq.ai.evaluation.dataset import EvalFinding
from critiq.ai.evaluation.metrics import measure
from critiq.core.findings import Finding, FindingSource
from critiq.core.policy import Category, Severity


def _pred(cat, path, line, sev=Severity.HIGH, conf=0.9):
    return Finding(
        category=cat, file_path=path, line_start=line, line_end=line,
        severity=sev, confidence=conf, title="t", explanation="e",
        evidence="v", recommendation="r", source=FindingSource.STATIC,
    )


def _exp(cat, path, line, sev=Severity.HIGH, useful=True):
    return EvalFinding(
        category=cat, file_path=path, line_start=line, severity=sev, useful=useful
    )


def test_measure_all_match():
    m = measure(
        "c1",
        [_pred(Category.SECURITY, "app/x.py", 3)],
        [_exp(Category.SECURITY, "app/x.py", 3)],
    )
    assert m.true_positives == 1
    assert m.false_positives == 0
    assert m.false_negatives == 0
    assert m.precision == 1.0
    assert m.recall == 1.0


def test_measure_false_positive_and_miss():
    m = measure(
        "c2",
        [_pred(Category.SECURITY, "app/x.py", 3)],  # matches
        [_exp(Category.SECURITY, "app/x.py", 3), _exp(Category.RELIABILITY, "app/y.py", 1)],
    )
    # predicted misses reliability expected (FN=1), no FP
    assert m.true_positives == 1
    assert m.false_positives == 0
    assert m.false_negatives == 1


def test_measure_line_tolerance():
    m = measure(
        "c3",
        [_pred(Category.SECURITY, "app/x.py", 4)],
        [_exp(Category.SECURITY, "app/x.py", 3)],
    )
    assert m.true_positives == 1
