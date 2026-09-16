import pytest

from critiq.core import profiles
from critiq.core.profiles import (
    ProfileNotFoundError,
    build_policy_yaml,
    load_profile,
    merge_configs,
)


def test_merge_configs_deep_merges_with_later_wins():
    merged = merge_configs(
        {
            "review": {
                "mode": "automatic",
                "model_routing": {"cheap": "a", "strong": "b"},
            }
        },
        {"review": {"severity_threshold": "high", "model_routing": {"strong": "c"}}},
    )
    assert merged == {
        "review": {
            "mode": "automatic",
            "severity_threshold": "high",
            "model_routing": {"cheap": "a", "strong": "c"},
        }
    }


def test_load_profile_reads_yaml_file(tmp_path, monkeypatch):
    (tmp_path / "backend.yml").write_text("review:\n  severity_threshold: high\n")
    monkeypatch.setattr(profiles.settings, "profiles_dir", str(tmp_path))
    assert load_profile("backend")["review"]["severity_threshold"] == "high"


def test_load_profile_raises_when_profile_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles.settings, "profiles_dir", str(tmp_path))
    with pytest.raises(ProfileNotFoundError):
        load_profile("nope")


def test_load_profile_raises_when_dir_unset(monkeypatch):
    monkeypatch.setattr(profiles.settings, "profiles_dir", "")
    with pytest.raises(ProfileNotFoundError):
        load_profile("nope")


def test_build_policy_yaml_merges_profile_with_repo_wins(tmp_path, monkeypatch):
    (tmp_path / "team.yml").write_text(
        "review:\n  severity_threshold: high\n  max_comments: 20\n"
    )
    monkeypatch.setattr(profiles.settings, "profiles_dir", str(tmp_path))

    merged = build_policy_yaml(
        "review:\n  profile: team\n  max_comments: 5\n  confidence_threshold: 0.9\n"
    )
    assert merged["review"]["severity_threshold"] == "high"
    assert merged["review"]["max_comments"] == 5
    assert merged["review"]["confidence_threshold"] == 0.9


def test_build_policy_yaml_merges_fix_profile_categories_then_repo_wins(tmp_path, monkeypatch):
    (tmp_path / "team.yml").write_text(
        "review:\n  fix:\n    enabled: true\n    categories: [security]\n    max_patches: 3\n"
    )
    monkeypatch.setattr(profiles.settings, "profiles_dir", str(tmp_path))

    merged = build_policy_yaml(
        "review:\n  profile: team\n  fix:\n    categories: [correctness]\n"
    )
    assert merged["review"]["fix"]["enabled"] is True
    assert merged["review"]["fix"]["max_patches"] == 3
    assert merged["review"]["fix"]["categories"] == ["correctness"]


def test_build_policy_yaml_without_profile_returns_repo_data():
    assert build_policy_yaml("review:\n  mode: approval\n") == {"review": {"mode": "approval"}}


def test_build_policy_yaml_falls_back_to_repo_only_when_profile_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles.settings, "profiles_dir", str(tmp_path))
    raw = "review:\n  profile: ghost\n  mode: advisory\n"
    assert build_policy_yaml(raw) == {"review": {"profile": "ghost", "mode": "advisory"}}


class _FakeClient:
    def __init__(self, raw):
        self.raw = raw

    async def get_file_content(self, repo, path, ref):
        if self.raw is None:
            raise RuntimeError("missing")
        return self.raw


@pytest.mark.asyncio
async def test_worker_load_policy_merges_profile(tmp_path, monkeypatch):
    from critiq.apps.worker import tasks

    (tmp_path / "team.yml").write_text("review:\n  severity_threshold: high\n")
    monkeypatch.setattr(profiles.settings, "profiles_dir", str(tmp_path))

    policy = await tasks._load_policy(
        _FakeClient("review:\n  profile: team\n  mode: approval\n"), "o/r"
    )
    assert policy.mode == "approval"
    assert policy.severity_threshold == "high"
