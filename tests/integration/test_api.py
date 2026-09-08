import hashlib
import hmac

from fastapi.testclient import TestClient

from critiq.apps.api.main import create_app


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
