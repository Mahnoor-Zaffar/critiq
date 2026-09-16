
from critiq.apps.worker.workspace import Workspace, WorkspaceManager


def test_apply_patch_replaces_target_lines(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    ws.apply_patch("app.py", 2, 3, "REPLACED")

    assert source.read_text(encoding="utf-8") == "line1\nREPLACED\nline4\nline5\n"


def test_apply_patch_allows_multiline_replacement(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("a\nb\nc\n", encoding="utf-8")
    ws = Workspace(tmp_path)

    ws.apply_patch("app.py", 2, 2, "X\nY")

    assert source.read_text(encoding="utf-8") == "a\nX\nY\nc\n"


def test_cache_path_is_based_on_base_sha(tmp_path):
    mgr = WorkspaceManager(str(tmp_path))
    assert mgr.base_cache_path("sha-aaa") == tmp_path / "base-sha-aaa"


def test_default_base_dir_creates_temp_directory():
    mgr = WorkspaceManager()
    assert mgr.base_dir.exists()
    assert "critiq-ws-" in str(mgr.base_dir)
