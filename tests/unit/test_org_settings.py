from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from critiq.apps.api.main import create_app
from critiq.apps.api.routers import org_settings as org_settings_mod
from critiq.core.config import settings
from critiq.infrastructure.postgres.models import OrgSetting, Repository


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, repo=None, setting=None):
        self._repo = repo
        self._setting = setting
        self.added = []

    async def get(self, model, pk):
        if model is Repository:
            return self._repo
        return None

    async def scalar(self, stmt):
        stmt_s = " ".join(str(stmt).split())
        if "OrgSetting" in stmt_s or "org_settings" in stmt_s:
            return self._setting
        return None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


class _SessionCtx:
    def __init__(self, session=None):
        self.session = session or _Session()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *a):
        return None


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "test-admin-token")


def _client(monkeypatch, session):
    ctx = _SessionCtx(session)
    monkeypatch.setattr(org_settings_mod, "async_session_factory", lambda: ctx)
    return TestClient(create_app())


def _auth(token="test-admin-token"):
    return {"Authorization": f"Bearer {token}"}


# -- GET tests --

def test_get_org_settings_401_when_no_token():
    resp = TestClient(create_app()).get("/api/org-settings/1")
    assert resp.status_code == 401


def test_get_org_settings_401_when_wrong_token():
    resp = TestClient(create_app()).get(
        "/api/org-settings/1", headers=_auth("wrong-token")
    )
    assert resp.status_code == 401


def test_get_org_settings_404_when_repo_not_found(monkeypatch):
    client = _client(monkeypatch, _Session(repo=None))
    resp = client.get("/api/org-settings/1", headers=_auth())
    assert resp.status_code == 404


def test_get_org_settings_returns_default_false(monkeypatch):
    client = _client(
        monkeypatch,
        _Session(repo=Repository(id=1, full_name="o/r"), setting=None),
    )
    resp = client.get("/api/org-settings/1", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["auto_push_enabled"] is False


def test_get_org_settings_returns_enabled(monkeypatch):
    setting = OrgSetting(repository_id=1, auto_push_enabled=True)
    client = _client(
        monkeypatch,
        _Session(repo=Repository(id=1, full_name="o/r"), setting=setting),
    )
    resp = client.get("/api/org-settings/1", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["auto_push_enabled"] is True


# -- PUT tests --

def test_put_org_settings_creates_new_setting(monkeypatch):
    session = _Session(repo=Repository(id=1, full_name="o/r"), setting=None)
    client = _client(monkeypatch, session)
    resp = client.put(
        "/api/org-settings/1",
        json={"auto_push_enabled": True},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["auto_push_enabled"] is True
    assert len(session.added) == 1


def test_put_org_settings_updates_existing_setting(monkeypatch):
    setting = OrgSetting(repository_id=1, auto_push_enabled=False)
    session = _Session(repo=Repository(id=1, full_name="o/r"), setting=setting)
    client = _client(monkeypatch, session)
    resp = client.put(
        "/api/org-settings/1",
        json={"auto_push_enabled": True},
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert setting.auto_push_enabled is True
    assert len(session.added) == 0


def test_put_org_settings_404_when_repo_not_found(monkeypatch):
    client = _client(monkeypatch, _Session(repo=None))
    resp = client.put(
        "/api/org-settings/1",
        json={"auto_push_enabled": True},
        headers=_auth(),
    )
    assert resp.status_code == 404
