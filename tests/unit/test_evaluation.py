from pathlib import Path

from critiq.ai.evaluation.dataset import load_dataset
from critiq.ai.evaluation.runner import render_report, run_evaluation
from critiq.ai.providers.mock import MockProvider


async def test_run_evaluation_matches_ground_truth():
    data = Path(__file__).parent.parent.parent / "datasets" / "sample.yml"
    cases = load_dataset(data)
    report = await run_evaluation(cases, provider=MockProvider())

    a = report.aggregate_data
    # With the mock provider, only static findings appear; both expected
    # security findings (secret + os.system) are caught.
    assert a["total_predicted"] == 2
    assert a["total_expected"] == 2
    assert a["precision"] == 1.0
    assert a["recall"] == 1.0
    assert a["false_positive_rate"] == 0.0

    text = render_report(report)
    assert "Critiq Evaluation Report" in text
    assert "security" in text
