import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from critiq.apps.api.main import create_app
from critiq.apps.api.routers import feedback as feedback_mod


def _sig(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_health():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_webhook_invalid_signature_rejected(monkeypatch):
    from critiq.core.config import settings

    monkeypatch.setattr(settings, "github_webhook_secret", "test-secret")
    client = TestClient(create_app())
    resp = client.post(
        "/webhooks/github",
        content=b'{"action":"opened"}',
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=0"},
    )
    assert resp.status_code == 401


def test_webhook_non_pull_request_event_accepted(monkeypatch):
    from critiq.core.config import settings

    payload = b'{"action":"create"}'
    monkeypatch.setattr(settings, "github_webhook_secret", "test-secret")
    client = TestClient(create_app())
    resp = client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-GitHub-Event": "push",
            "X-Hub-Signature-256": _sig(payload, "test-secret"),
        },
    )
    assert resp.status_code == 200


class _FbResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        class _S:
            def all(self_):
                return self._rows

        return _S()


class _FbSession:
    def __init__(self):
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def scalar(self, stmt):
        return 7

    async def execute(self, stmt):
        s = " ".join(str(stmt).split())
        if "GROUP BY finding_feedback.signal" in s:
            return _FbResult([("accepted", 5), ("rejected", 2)])
        if "finding_feedback.finding_id" in s:
            return _FbResult([])
        raise AssertionError(f"unhandled statement: {s}")


@pytest.fixture(autouse=True)
def _fake_feedback_session(monkeypatch):
    monkeypatch.setattr(feedback_mod, "async_session_factory", _FbSession)


def test_feedback_api_post_records_signal():
    client = TestClient(create_app())
    resp = client.post(
        "/api/feedback/findings/1",
        json={"signal": "accepted", "note": "good"},
    )
    assert resp.status_code == 201
    assert resp.json()["signal"] == "accepted"


def test_feedback_api_post_rejects_bad_signal():
    client = TestClient(create_app())
    resp = client.post("/api/feedback/findings/1", json={"signal": "meh"})
    assert resp.status_code == 422


def test_feedback_api_list_returns_feedback():
    client = TestClient(create_app())
    resp = client.get("/api/feedback/findings/1")
    assert resp.status_code == 200
    assert resp.json() == []


def test_feedback_api_stats_returns_aggregates():
    client = TestClient(create_app())
    resp = client.get("/api/feedback/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 7
    assert body["by_signal"] == {"accepted": 5, "rejected": 2}
    assert body["acceptance_rate"] == 71.4
