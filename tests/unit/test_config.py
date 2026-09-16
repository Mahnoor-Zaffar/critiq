from critiq.core.config import Settings


def test_autofix_settings_defaults():
    settings = Settings()
    assert settings.admin_token == ""
    assert settings.test_timeout_seconds == 60.0
    assert settings.workspace_dir == ""


def test_autofix_settings_from_env(monkeypatch):
    monkeypatch.setenv("CRITIQ_ADMIN_TOKEN", "sekret")
    monkeypatch.setenv("CRITIQ_TEST_TIMEOUT_SECONDS", "75")
    monkeypatch.setenv("CRITIQ_WORKSPACE_DIR", "/tmp/ws")
    settings = Settings(_env_file=None)
    assert settings.admin_token == "sekret"
    assert settings.test_timeout_seconds == 75.0
    assert settings.workspace_dir == "/tmp/ws"
