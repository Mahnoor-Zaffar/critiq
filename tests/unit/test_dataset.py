from pathlib import Path

from critiq.ai.evaluation.dataset import load_dataset


def test_load_dataset_from_file(tmp_path):
    data = Path(__file__).parent.parent.parent / "datasets" / "sample.yml"
    cases = load_dataset(data)
    assert len(cases) == 1
    case = cases[0]
    assert case.id == "case-secret"
    assert len(case.files) == 1
    assert len(case.expected) == 2
    assert case.sources["app/handler.py"].strip().startswith("import os")
