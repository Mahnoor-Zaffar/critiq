import pytest

from critiq.ai.providers.mock import MockProvider
from critiq.apps.worker import review_service
from critiq.apps.worker.feedback_stats import load_feedback_stats
from critiq.core.feedback import ConfidenceCalibrator, FeedbackStats
from critiq.core.findings import ReviewResult
from critiq.integrations.github.client import ChangedFile

PATCH = """@@ -1,3 +1,6 @@
 import os
+
+TOKEN = "x"
"""


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _RepoScopeSession:
    def __init__(self):
        self.global_called = False

    async def execute(self, stmt):
        s = " ".join(str(stmt).split())
        if "repositories.full_name" in s:
            return _Result([("security", 20, 16, 2)])
        self.global_called = True
        return _Result([])


class _EmptyRepoSession:
    def __init__(self):
        self.repo_called = False

    async def execute(self, stmt):
        s = " ".join(str(stmt).split())
        if "repositories.full_name" in s:
            self.repo_called = True
            return _Result([])
        return _Result([("testing", 5, 1, 3)])


@pytest.mark.asyncio
async def test_load_feedback_stats_uses_repo_scope_when_available():
    session = _RepoScopeSession()
    stats = await load_feedback_stats(session, "o/r")

    assert stats["security"] == FeedbackStats(
        category="security", total=20, accepted=16, resolved=2
    )
    assert session.global_called is False


@pytest.mark.asyncio
async def test_load_feedback_stats_falls_back_to_global():
    session = _EmptyRepoSession()
    stats = await load_feedback_stats(session, "o/r")

    assert session.repo_called is True
    assert stats["testing"] == FeedbackStats(
        category="testing", total=5, accepted=1, resolved=3
    )


@pytest.mark.asyncio
async def test_load_feedback_stats_returns_empty_for_no_feedback():
    class _NoFeedbackSession:
        async def execute(self, stmt):
            s = " ".join(str(stmt).split())
            if "repositories.full_name" in s:
                return _Result([])
            return _Result([])

    assert await load_feedback_stats(_NoFeedbackSession(), "o/r") == {}


class _FakeClient:
    async def get_pull_request(self, repo, number):
        return {"head": {"sha": "abc123"}}

    async def get_pull_files(self, repo, number):
        return [
            ChangedFile(
                filename="app/x.py",
                status="modified",
                additions=2,
                deletions=0,
                patch=PATCH,
            )
        ]

    async def get_file_content(self, repo, path, ref):
        return "import os\n\nTOKEN = 'x'\n"


@pytest.mark.asyncio
async def test_review_service_builds_calibrator_from_feedback(monkeypatch):
    received = {}

    async def run_stub(*args, **kwargs):
        received["calibrator"] = kwargs.get("calibrator")
        return ReviewResult()

    monkeypatch.setattr(review_service, "run_review", run_stub)
    await review_service.review_pull_request(
        _FakeClient(),
        "o/r",
        1,
        session=_RepoScopeSession(),
        policy=None,
        provider=MockProvider(),
    )

    calibrator = received["calibrator"]
    assert isinstance(calibrator, ConfidenceCalibrator)
    assert calibrator.calibrate(0.5, "security") == pytest.approx(0.58)


@pytest.mark.asyncio
async def test_review_service_skips_calibration_without_session(monkeypatch):
    received = {}

    async def run_stub(*args, **kwargs):
        received["calibrator"] = kwargs.get("calibrator")
        return ReviewResult()

    monkeypatch.setattr(review_service, "run_review", run_stub)
    await review_service.review_pull_request(
        _FakeClient(),
        "o/r",
        1,
        session=None,
        policy=None,
        provider=MockProvider(),
    )

    assert received["calibrator"] is None
