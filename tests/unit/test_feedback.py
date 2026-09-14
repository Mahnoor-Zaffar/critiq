from critiq.core.feedback import (
    ConfidenceAdjuster,
    ConfidenceCalibrator,
    FeedbackSignal,
    FeedbackStats,
)


def test_boost_on_accept():
    assert ConfidenceAdjuster().adjust(0.8, FeedbackSignal.ACCEPTED) == 0.85


def test_penalty_on_reject():
    assert ConfidenceAdjuster().adjust(0.8, FeedbackSignal.REJECTED) == 0.7


def test_resolve_boosts_like_accept():
    assert ConfidenceAdjuster().adjust(0.8, FeedbackSignal.RESOLVED) == 0.85


def test_clamped_at_bounds():
    adjuster = ConfidenceAdjuster()
    assert adjuster.adjust(0.98, FeedbackSignal.ACCEPTED) == 1.0
    assert adjuster.adjust(0.05, FeedbackSignal.REJECTED) == 0.0


def _stats(total, accepted, resolved=0):
    return FeedbackStats(category="security", total=total, accepted=accepted, resolved=resolved)


def test_calibrator_unchanged_without_history():
    assert ConfidenceCalibrator({}).calibrate(0.8, "security") == 0.8
    assert ConfidenceCalibrator({}).calibrate(0.8, "anything") == 0.8


def test_calibrator_boosts_high_acceptance_category():
    stats = {"security": _stats(total=30, accepted=27, resolved=0)}
    assert ConfidenceCalibrator(stats).calibrate(0.7, "security") == 0.78


def test_calibrator_reduces_rejected_category():
    stats = {"testing": FeedbackStats("testing", 30, 3, 0)}
    assert ConfidenceCalibrator(stats).calibrate(0.8, "testing") == 0.72


def test_calibrator_resolved_counts_as_positive():
    stats = {"security": _stats(total=10, accepted=0, resolved=10)}
    assert ConfidenceCalibrator(stats).calibrate(0.5, "security") == 0.5667


def test_calibrator_scales_with_evidence():
    stats = {"security": _stats(total=7, accepted=7, resolved=0)}
    expected = round(0.8 + 0.1 * (7 / 15), 4)
    assert ConfidenceCalibrator(stats).calibrate(0.8, "security") == expected


def test_calibrator_clamps_at_bounds():
    boosted = {"security": _stats(total=30, accepted=30, resolved=0)}
    assert ConfidenceCalibrator(boosted).calibrate(0.99, "security") == 1.0
    rejected = {"testing": FeedbackStats("testing", 30, 0, 0)}
    assert ConfidenceCalibrator(rejected).calibrate(0.05, "testing") == 0.0
