import pytest

from critiq.ai.providers.mock import MockProvider
from critiq.apps.worker import review_service
from critiq.apps.worker import tasks as worker_tasks
from critiq.core.findings import Finding, FindingSource, ReviewResult
from critiq.core.policy import Category, ReviewPolicy, Severity
from critiq.integrations.github.client import ChangedFile

PATCH = """@@ -1,3 +1,7 @@
 import os
+
+API_KEY = "sk-123456"
+
+def run():
+    return os.system("echo hi")
"""

SOURCE = (
    'import os\n\nAPI_KEY = "sk-123456"\n\ndef run():\n    return os.system("echo hi")\n'
)


class FakeGitHubClient:
    """In-memory GitHub client that records posted reviews."""

    def __init__(self, files=None, contents=None):
        self.pr = {"head": {"sha": "abc123"}}
        self.files = files or [
            ChangedFile(
                filename="app/handler.py",
                status="modified",
                additions=3,
                deletions=0,
                patch=PATCH,
            )
        ]
        self.contents = contents or {"app/handler.py": SOURCE}
        self.created_reviews = []

    async def get_pull_request(self, repo, number):
        return self.pr

    async def get_pull_files(self, repo, number):
        return self.files

    async def get_file_content(self, repo, path, ref):
        return self.contents.get(path)

    async def create_review(self, repo, number, body, comments, event="COMMENT"):
        self.created_reviews.append(
            {"repo": repo, "number": number, "body": body,
             "comments": comments, "event": event}
        )
        return {"id": 1}


@pytest.mark.asyncio
async def test_review_flow_full_loop_with_mock_llm():
    client = FakeGitHubClient()
    policy = ReviewPolicy.defaults()

    result = await review_service.review_pull_request(
        client, "o/r", 1, session=None, policy=policy, provider=MockProvider()
    )

    assert result.findings, "expected static findings (secret + os.system)"
    assert all(f.category.value == "security" for f in result.findings)

    await review_service.post_review(client, "o/r", 1, result)
    assert len(client.created_reviews) == 1
    posted = client.created_reviews[0]
    assert "Critiq Review" in posted["body"]
    assert posted["comments"], "expected line comments"
    assert posted["comments"][0].file_path == "app/handler.py"


class _FakeSession:
    async def commit(self):
        return None


class _FakeRun:
    def __init__(self):
        self.id = 7
        self.status = "pending"
        self.decision = None
        self.summary = None
        self.error = None


@pytest.mark.asyncio
async def test_worker_task_pipelines_and_posts(monkeypatch):
    posted = []
    run = _FakeRun()

    class FakeAuth:
        def __init__(self, app_id="", private_key=""):
            self.app_id = app_id
            self.private_key = private_key

        async def get_installation_token(self, installation_id):
            return "tok"

    class FakeSessionCtx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return None

    async def policy_stub(client, repo):
        return ReviewPolicy.defaults()

    async def upsert_stub(session, repo, number):
        return run

    async def save_stub(session, run_id, result):
        return None

    async def pipeline_stub(diffs, fetch, provider, policy=None, policy_yaml=""):
        return ReviewResult(
            decision="COMMENT",
            risk="LOW",
            summary="ok",
            findings=[
                Finding(
                    category=Category.SECURITY, file_path="app/handler.py",
                    line_start=3, line_end=3, title="secret", explanation="e",
                    evidence="v", recommendation="r", severity=Severity.HIGH,
                    confidence=0.96, source=FindingSource.STATIC,
                )
            ],
            comments=[],
        )

    async def post_stub(client, repo, number, result, event="COMMENT"):
        posted.append((repo, number, result.decision))

    monkeypatch.setattr(worker_tasks, "GitHubAuth", FakeAuth)
    monkeypatch.setattr(worker_tasks, "GitHubClient", lambda token: FakeGitHubClient())
    monkeypatch.setattr(worker_tasks, "async_session_factory", FakeSessionCtx)
    monkeypatch.setattr(worker_tasks, "_load_policy", policy_stub)
    monkeypatch.setattr(worker_tasks, "_upsert_run", upsert_stub)
    monkeypatch.setattr(worker_tasks, "_save_findings", save_stub)
    monkeypatch.setattr(worker_tasks, "run_review_pipeline", pipeline_stub)
    monkeypatch.setattr(worker_tasks, "post_review", post_stub)

    await worker_tasks.review_pull_request({}, installation_id=1, repo="o/r", number=1)

    assert posted == [("o/r", 1, "COMMENT")]
    assert run.status == "success"
    assert run.decision == "COMMENT"
