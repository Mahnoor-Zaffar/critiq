from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from critiq.apps.api import dashboard as dash
from critiq.apps.api.main import create_app

_REPO = SimpleNamespace(
    id=1, full_name="o/r", default_branch="main", last_analyzed_at=None
)
_PR = SimpleNamespace(
    id=10, repository_id=1, github_pr_number=12, title="Add auth",
    state="open", head_branch="feat/auth", head_sha="abc123",
)
_RUN = SimpleNamespace(
    id=7, pull_request_id=10, status="success", mode="automatic",
    decision="COMMENT", summary="Looks good overall.",
    started_at=datetime(2026, 9, 1, 10, 0),
    completed_at=datetime(2026, 9, 1, 10, 1), error=None,
)
_FINDING_1 = SimpleNamespace(
    id=1, review_run_id=7, category="security", file_path="app/handler.py",
    line_start=3, line_end=3, severity="high", confidence=0.96,
    title="Hardcoded secret", explanation="A secret is baked in.",
    evidence="`API_KEY = \"sk-123\"` on line 3.",
    recommendation="Use env vars.",
)
_FINDING_2 = SimpleNamespace(
    id=2, review_run_id=7, category="testing", file_path="app/handler.py",
    line_start=5, line_end=5, severity="low", confidence=0.7,
    title="Missing test", explanation="No test covers this.",
    evidence="cf. app/test_handler.py", recommendation="Add a test.",
)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return _Scalars(self._rows)


class _Session:
    def __init__(self, run_detail_rows=None, repo_detail_rows=None):
        self.run_detail_rows = run_detail_rows
        self.repo_detail_rows = repo_detail_rows

    async def get(self, model, pk):
        return _FINDING_1 if pk == 1 else None

    async def add(self, obj):
        return None

    async def commit(self):
        return None

    async def execute(self, stmt):
        s = " ".join(str(stmt).split())
        if "WHERE review_runs.id" in s and "JOIN pull_requests" in s:
            rows = self.run_detail_rows
            return _Result(rows if rows is not None else [(_RUN, _PR, _REPO)])
        if "FROM review_runs JOIN pull_requests" in s:
            return _Result([(_RUN, _PR, _REPO, 2), (_RUN, _PR, _REPO, 1)])
        if "count(" in s:
            if "finding_feedback" in s and "GROUP BY finding_feedback.signal" in s:
                return _Result([("accepted", 5), ("rejected", 2)])
            if "finding_feedback" in s and "GROUP BY findings.category" in s:
                return _Result([("security", "accepted", 4), ("testing", "rejected", 1)])
            if "finding_feedback" in s:
                return _Result([7])
            if "GROUP BY findings.severity" in s:
                return _Result([("high", 3), ("low", 1)])
            if "GROUP BY findings.category" in s:
                return _Result([("security", 2), ("testing", 1)])
            if "JOIN review_runs" in s and "GROUP BY pull_requests.repository_id" in s:
                return _Result([(1, 2)])
            if "GROUP BY pull_requests.repository_id" in s:
                return _Result([(1, 3)])
            if "FROM repositories" in s:
                return _Result([1])
            if "FROM pull_requests" in s:
                return _Result([2])
            if "FROM review_runs" in s:
                return _Result([4])
            if "FROM findings" in s:
                return _Result([5])
        if "FROM repositories WHERE" in s:
            rows = self.repo_detail_rows
            return _Result(rows if rows is not None else [_REPO])
        if "SELECT repositories.full_name" in s:
            return _Result(["o/r"])
        if "FROM repositories ORDER BY" in s:
            return _Result([_REPO])
        if "FROM pull_requests WHERE" in s:
            return _Result([_PR])
        if "FROM findings WHERE" in s:
            return _Result([_FINDING_1, _FINDING_2])
        if "finding_feedback" in s and "WHERE finding_feedback.finding_id" in s:
            return _Result([])
        if "FROM finding_feedback JOIN findings" in s:
            return _Result([])
        raise AssertionError(f"unhandled statement: {s}")


class _SessionCtx:
    def __init__(self, session=None):
        self.session = session or _Session()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *a):
        return None


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(dash, "async_session_factory", lambda: _SessionCtx())
    monkeypatch.setattr(dash.settings, "repo_index_dir", str(tmp_path / "indexes"))
    return TestClient(create_app())


def test_root_links_to_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["dashboard"] == "/dashboard"


def test_overview_renders_stats(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    text = resp.text
    assert "Overview" in text
    assert "Repositories" in text and "Findings" in text
    assert "Review run" in text and "#7" in text
    assert "o/r" in text


def test_repos_page_lists_repositories(client):
    res = client.get("/dashboard/repos")
    assert res.status_code == 200
    assert "o/r" in res.text
    assert "not indexed" in res.text


def test_repo_detail_renders_intelligence(client, tmp_path, monkeypatch):
    from critiq.repository.store import IndexCache, build_index

    checkout = tmp_path / "checkout"
    (checkout / "app").mkdir(parents=True)
    (checkout / "app" / "service.py").write_text(
        "import os\nfrom app.db import DB\n\ndef run():\n    db = DB()\n    return db.query()\n"
    )
    (checkout / "app" / "db.py").write_text("class DB:\n    def query(self):\n        return 1\n")
    cache_dir = tmp_path / "idx"
    IndexCache(str(cache_dir)).save("o/r", build_index(checkout))
    monkeypatch.setattr(dash.settings, "repo_index_dir", str(cache_dir))

    resp = client.get("/dashboard/repos/1")
    assert resp.status_code == 200
    text = resp.text
    assert "o/r" in text
    assert "Repository intelligence" in text
    assert "app/service.py" in text
    assert "#12" in text and "Add auth" in text
    assert "Recent review runs" in text


def test_repo_detail_missing_returns_404(monkeypatch):
    session = _Session(repo_detail_rows=[])
    monkeypatch.setattr(dash, "async_session_factory", lambda: _SessionCtx(session))
    client = TestClient(create_app())
    resp = client.get("/dashboard/repos/999")
    assert resp.status_code == 404


def test_runs_history_page_with_filter(client):
    resp = client.get("/dashboard/runs?repo=o/r")
    assert resp.status_code == 200
    text = resp.text
    assert "Review history" in text
    assert "o/r" in text
    assert "COMMENT" in text


def test_run_detail_renders_findings(client):
    resp = client.get("/dashboard/runs/7")
    assert resp.status_code == 200
    text = resp.text
    assert "Hardcoded secret" in text
    assert "app/handler.py" in text
    assert "high" in text and "security" in text
    assert "Recommendation:" in text


def test_run_detail_missing_returns_404(monkeypatch):
    monkeypatch.setattr(
        dash, "async_session_factory", lambda: _SessionCtx(_Session(run_detail_rows=[]))
    )
    client = TestClient(create_app())
    resp = client.get("/dashboard/runs/999")
    assert resp.status_code == 404


def test_submit_feedback_records_signal(client):
    resp = client.post(
        "/dashboard/findings/1/feedback",
        data={"signal": "accepted", "note": "nice catch"},
    )
    assert resp.status_code == 200
    assert "accepted" in resp.text
    assert "finding" in resp.text


def test_submit_feedback_invalid_signal(client):
    resp = client.post("/dashboard/findings/1/feedback", data={"signal": "meh"})
    assert resp.status_code == 400


def test_feedback_page_renders_analytics(client):
    resp = client.get("/dashboard/feedback")
    assert resp.status_code == 200
    text = resp.text
    assert "Feedback" in text
    assert "Acceptance rate" in text
    assert "Recent responses" in text


def test_static_css_served(client):
    resp = client.get("/static/dashboard.css")
    assert resp.status_code == 200
    assert "--bg" in resp.text
