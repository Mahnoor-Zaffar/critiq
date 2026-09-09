from critiq.repository.store import IndexCache, build_index


def _make_repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "service.py").write_text(
        "import os\nfrom app.db import Con\n\ndef run():\n    return 1\n"
    )
    (tmp_path / "app" / "db.py").write_text("class Con:\n    pass\n")
    return tmp_path


def test_build_index(tmp_path):
    repo = _make_repo(tmp_path)
    index = build_index(repo)
    assert index.file_count == 2
    assert index.symbols_for("app/service.py")  # function 'run'
    assert "app/db.py" in index.related_for_change("app/service.py")


def test_index_roundtrip(tmp_path):
    repo = _make_repo(tmp_path)
    index = build_index(repo)
    data = index.to_dict()
    restored = index.from_dict(data)
    assert restored.file_count == index.file_count
    assert restored.modules["app/service.py"].imports == [
        "import os",
        "from app.db import Con",
    ]


def test_index_cache(tmp_path):
    repo = _make_repo(tmp_path)
    cache = IndexCache(tmp_path / "cache")
    idx = cache.get_or_build("owner/repo@sha", repo)
    assert idx.file_count == 2
    # Second call should load from cache (same result)
    idx2 = cache.get_or_build("owner/repo@sha", repo)
    assert idx2.file_count == idx.file_count
    assert cache.path_for("owner/repo@sha").exists()
