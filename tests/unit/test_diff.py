from critiq.analysis.diff import parse_patch

PATCH = """diff --git a/app/review.py b/app/review.py
index 0000000..1111111 100644
--- a/app/review.py
+++ b/app/review.py
@@ -1,3 +1,8 @@
 import os
+
+SECRET = "sk-1234"
+
+def run():
+    os.system("echo hi")
"""


def test_parse_patch_tracks_added_lines():
    fd = parse_patch("app/review.py", PATCH)
    assert fd.path == "app/review.py"
    # `import os` is context (new line 1); added lines are new lines 2..6
    assert fd.added_lines == [2, 3, 4, 5, 6]
    assert fd.is_line_added(3)
    assert not fd.is_line_added(1)


def test_parse_patch_empty_patch():
    fd = parse_patch("app/x.py", None)
    assert fd.added_lines == []
