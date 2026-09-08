from critiq.analysis.diff import parse_patch
from critiq.analysis.static import StaticAnalyzer
from critiq.core.policy import Category


def _context_with_source(path: str, source: str):
    from critiq.analysis.ast import PythonParser
    from critiq.analysis.context import RepoContext

    ctx = RepoContext()
    info = PythonParser().parse_module(path, source)
    ctx.modules[path] = info
    return ctx


PATCH = """@@ -1,3 +1,8 @@
 import os
+
+SECRET = "sk-1234"
+
+def run():
+    os.system("echo hi")
"""


def test_static_detects_secret_and_os_system():
    path = "app/review.py"
    source = 'import os\n\nSECRET = "sk-1234"\n\ndef run():\n    os.system("echo hi")\n'
    analyzer = StaticAnalyzer()
    findings = analyzer.analyze(_context_with_source(path, source), parse_patch(path, PATCH))
    cats = {f.category for f in findings}
    assert Category.SECURITY in cats
    assert any(f.title.lower().startswith("hardcoded") for f in findings)
    assert any("os.system" in f.title.lower() for f in findings)
