import asyncio

from critiq.apps.worker.test_runner import (
    PASSED,
    UNVERIFIED,
    PatchStatus,
    discover_target_tests,
)


def test_discover_returns_self_when_changed_file_is_a_test(tmp_path):
    f = tmp_path / "tests" / "test_handler.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("#")
    found = discover_target_tests(tmp_path, "tests/test_handler.py")
    assert [p.name for p in found] == ["test_handler.py"]


def test_discover_returns_sibling_test(tmp_path):
    src = tmp_path / "app" / "handler.py"
    test = tmp_path / "app" / "test_handler.py"
    src.parent.mkdir()
    src.write_text("#")
    test.write_text("#")
    found = discover_target_tests(tmp_path, "app/handler.py")
    assert [p.name for p in found] == ["test_handler.py"]


def test_discover_returns_tests_mirror(tmp_path):
    src = tmp_path / "app" / "handler.py"
    test = tmp_path / "tests" / "app" / "test_handler.py"
    src.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    src.write_text("#")
    test.write_text("#")
    found = discover_target_tests(tmp_path, "app/handler.py")
    assert [p.name for p in found] == ["test_handler.py"]


def test_discover_returns_empty_for_non_python(tmp_path):
    assert discover_target_tests(tmp_path, "style.css") == []


def test_discover_returns_empty_for_missing_file(tmp_path):
    assert discover_target_tests(tmp_path, "missing.py") == []


def test_discover_prefer_sibling_not_duplicated(tmp_path):
    src = tmp_path / "x" / "mod.py"
    test_sibling = tmp_path / "x" / "test_mod.py"
    test_mirror = tmp_path / "tests" / "x" / "test_mod.py"
    src.parent.mkdir()
    test_mirror.parent.mkdir(parents=True)
    src.write_text("#")
    test_sibling.write_text("#")
    test_mirror.write_text("#")
    found = discover_target_tests(tmp_path, "x/mod.py")
    assert len(found) == 2
    assert found[0].name == "test_mod.py" and found[0].parent == src.parent


def test_fake_runner_is_called_for_candidates(tmp_path):
    calls: list[str] = []
    src = tmp_path / "mod.py"
    test = tmp_path / "test_mod.py"
    src.write_text("#")
    test.write_text("#")

    async def fake_runner(root, candidate, timeout):
        calls.append(str(candidate))
        return PatchStatus(PASSED, "fake")

    async def _run():
        candidates = discover_target_tests(tmp_path, "mod.py")
        for c in candidates:
            return await fake_runner(tmp_path, c, 10.0)
        return PatchStatus(UNVERIFIED, "no candidates")

    result = asyncio.run(_run())
    assert result.status == PASSED
    assert calls
