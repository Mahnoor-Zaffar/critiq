import re

from critiq.ai.history import HistoryBlock, HistoryStatus, PathHistory
from critiq.ai.providers.mock import MockProvider
from critiq.analysis.diff import parse_patch
from critiq.core.policy import ReviewPolicy
from critiq.pipeline import run_review

PATCH = """@@ -1,5 +1,10 @@
 import os
+
+SECRET = "sk-1234"
+
+def run():
+    os.system("echo hi")
+
+def handle():
+    return run()
"""

SOURCE = (
    'import os\n\nSECRET = "sk-1234"\n\ndef run():\n    os.system("echo hi")\n'
    "\ndef handle():\n    return run()\n"
)

OTHER_PATCH = """@@ -1,2 +1,5 @@
 import os
+
+def other():
+    return os.getcwd()
"""

OTHER_SOURCE = "import os\n\ndef other():\n    return os.getcwd()\n"


async def test_run_review_end_to_end_with_mock():
    policy = ReviewPolicy.defaults()

    async def fetch(path: str) -> str | None:
        return SOURCE if path == "app/review.py" else None

    result = await run_review(
        [parse_patch("app/review.py", PATCH)],
        fetch,
        MockProvider(),
        policy=policy,
    )
    # Static analyzer should contribute at least a security finding for the secret.
    cats = {f.category for f in result.findings}
    assert "security" in {c.value for c in cats}


class RecordingProvider:
    """Records every user prompt; answers reviewer and synthesis schemas."""

    def __init__(self):
        self.users = []

    async def generate(self, *, system, user, schema=None):
        self.users.append(user)
        if schema and "decision" in schema:
            return {"decision": "COMMENT", "risk": "LOW", "summary": "ok"}
        return {"findings": []}


async def test_run_review_sends_each_reviewer_only_its_own_files_history():
    policy = ReviewPolicy.defaults()
    sources = {"app/review.py": SOURCE, "app/other.py": OTHER_SOURCE}

    async def fetch(path: str) -> str | None:
        return sources.get(path)

    block = HistoryBlock(
        entries={
            "app/review.py": PathHistory(
                "app/review.py",
                HistoryStatus.OK,
                ("- Changed in abc1234: fix null check",),
                ("- Previously flagged in Run 42 (security): hardcoded secret",),
            ),
            "app/other.py": PathHistory(
                "app/other.py", HistoryStatus.OK, ("- Changed in def9012: unrelated",)
            ),
        },
        changed_file_count=2,
    )
    provider = RecordingProvider()
    await run_review(
        [parse_patch("app/review.py", PATCH), parse_patch("app/other.py", OTHER_PATCH)],
        fetch,
        provider,
        policy=policy,
        history=block,
    )

    reviewer_users, synthesizer_user = provider.users[:-1], provider.users[-1]
    by_file: dict[str, list[str]] = {}
    for user in reviewer_users:
        judged = re.search(r"Changed file: `([^`]+)`", user)
        assert judged, f"a reviewer prompt did not name the file it judges:\n{user}"
        by_file.setdefault(judged.group(1), []).append(user)

    assert set(by_file) == {"app/review.py", "app/other.py"}
    assert len(by_file["app/review.py"]) == 6, "six categories judge the first file"
    for user in by_file["app/review.py"]:
        assert "Recorded history for the file you are reviewing" in user
        assert "Changed in abc1234" in user
        assert "def9012" not in user, "a reviewer must not read another file's history"
    for user in by_file["app/other.py"]:
        assert "Changed in def9012" in user
        assert "abc1234" not in user, "a reviewer must not read another file's history"

    assert "abc1234" in synthesizer_user
    assert "def9012" in synthesizer_user, "the synthesizer keeps the cross file view"
    assert "Findings:" in synthesizer_user


async def test_run_review_omits_history_when_there_is_none():
    policy = ReviewPolicy.defaults()

    async def fetch(path: str) -> str | None:
        return SOURCE if path == "app/review.py" else None

    provider = RecordingProvider()
    await run_review(
        [parse_patch("app/review.py", PATCH)],
        fetch,
        provider,
        policy=policy,
    )

    assert all("Recorded history" not in u for u in provider.users[:-1])
    assert "Recorded history" not in provider.users[-1]


async def test_run_review_applies_custom_rule():
    policy = ReviewPolicy(
        {
            "review": {
                "severity_threshold": "low",
                "rules": [
                    {
                        "id": "no-secrets",
                        "name": "No hardcoded secrets",
                        "description": "Secrets must come from env vars.",
                        "severity": "low",
                        "categories": ["security"],
                        "patterns": ["SECRET\\s*="],
                    }
                ],
            }
        }
    )

    async def fetch(path: str) -> str | None:
        return SOURCE if path == "app/review.py" else None

    result = await run_review(
        [parse_patch("app/review.py", PATCH)],
        fetch,
        MockProvider(),
        policy=policy,
    )
    titles = {f.title for f in result.findings}
    assert "No hardcoded secrets" in titles
