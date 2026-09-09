from critiq.core.feedback import ConfidenceAdjuster, FeedbackSignal


def test_boost_on_accept():
    assert ConfidenceAdjuster().adjust(0.8, FeedbackSignal.ACCEPTED) == 0.85


def test_penalty_on_reject():
    assert ConfidenceAdjuster().adjust(0.8, FeedbackSignal.REJECTED) == 0.7


def test_clamped_at_bounds():
    adjuster = ConfidenceAdjuster()
    assert adjuster.adjust(0.98, FeedbackSignal.ACCEPTED) == 1.0
    assert adjuster.adjust(0.05, FeedbackSignal.REJECTED) == 0.0
