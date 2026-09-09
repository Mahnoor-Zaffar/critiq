from critiq.analysis.context import ContextBuilder
from critiq.analysis.diff import parse_patch
from critiq.repository.store import build_index


def _make_repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "service.py").write_text(
        "import os\nfrom app.db import DB\n\ndef run():\n    db = DB()\n    return db.query()\n"
    )
    (tmp_path / "app" / "db.py").write_text(
        "class DB:\n    def query(self):\n        return 1\n"
    )
    return tmp_path


async def test_context_builder_uses_index_for_related_files(tmp_path):
    repo = _make_repo(tmp_path)
    index = build_index(repo)
    patch = """@@ -1,4 +1,6 @@
 import os
+from app.db import DB
+
 def run():
-    return None
+    db = DB()
+    return db.query()
"""

    async def fetch(path: str) -> str | None:
        return None  # no external fetch: related must come from the index

    context = await ContextBuilder().build(
        changed_files=[parse_patch("app/service.py", patch)],
        fetch=fetch,
        repo_index=index,
    )
    assert "app/db.py" in context.related_files
    assert "class DB" in context.related_files["app/db.py"]
