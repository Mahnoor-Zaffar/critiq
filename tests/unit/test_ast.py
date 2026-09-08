from critiq.analysis.ast import PythonParser


def test_parse_module_extracts_symbols_and_imports():
    source = (
        "import os\nfrom foo import bar\n\nclass Service:\n    pass\n"
        "\ndef run():\n    return 1\n"
    )
    info = PythonParser().parse_module("app/service.py", source)
    assert info.imports == ["import os", "from foo import bar"]
    names = {s.name for s in info.top_level_symbols}
    assert "Service" in names
    assert "run" in names
