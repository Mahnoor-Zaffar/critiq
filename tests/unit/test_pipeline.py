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


async def test_run_review_injects_history_into_reviewer_and_synthesizer():
    policy = ReviewPolicy.defaults()

    async def fetch(path: str) -> str | None:
        return SOURCE if path == "app/review.py" else None

    provider = RecordingProvider()
    history = "app/review.py\n- Changed in abc1234: fix null check"
    await run_review(
        [parse_patch("app/review.py", PATCH)],
        fetch,
        provider,
        policy=policy,
        history=history,
    )

    reviewer_users, synthesizer_user = provider.users[:-1], provider.users[-1]
    assert any("## History Context" in u and "Changed in abc1234" in u for u in reviewer_users)
    assert "History context" in synthesizer_user
    assert "Changed in abc1234" in synthesizer_user
    assert "Findings:" in synthesizer_user


async def test_run_review_omits_history_context_when_empty():
    policy = ReviewPolicy.defaults()

    async def fetch(path: str) -> str | None:
        return SOURCE if path == "app/review.py" else None

    provider = RecordingProvider()
    await run_review(
        [parse_patch("app/review.py", PATCH)],
        fetch,
        provider,
        policy=policy,
        history="",
    )

    assert all("History Context" not in u for u in provider.users[:-1])
    assert "History context" not in provider.users[-1]


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
