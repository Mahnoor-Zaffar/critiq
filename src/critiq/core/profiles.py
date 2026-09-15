from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from critiq.core.config import settings

logger = logging.getLogger("critiq.profiles")


class ProfileNotFoundError(KeyError):
    pass


def load_profile(name: str) -> dict[str, Any]:
    """Load a team profile by name from the configured profiles directory.

    Raises ProfileNotFoundError if the directory is unset or the profile file
    is missing.
    """
    if not settings.profiles_dir:
        raise ProfileNotFoundError(
            "profiles_dir is not configured (set CRITIQ_PROFILES_DIR)"
        )
    path = Path(settings.profiles_dir) / f"{name}.yml"
    if not path.exists():
        raise ProfileNotFoundError(f"profile not found: {name}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ProfileNotFoundError(f"profile {name} is not a YAML mapping")
    return data


def merge_configs(*configs: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge YAML configs; later dicts win at every level."""
    merged: dict[str, Any] = {}
    for config in configs:
        _deep_merge(merged, config or {})
    return merged


def build_policy_yaml(raw: str | None) -> dict[str, Any]:
    """Merge a repo's `.critiq.yml` content over its referenced team profile.

    Precedence: defaults < profile < repo `.critiq.yml`. If the repo declares
    `review.profile` and that profile can't be loaded, the repo config is used
    alone so a misconfigured profile never blocks reviews.
    """
    repo_data = yaml.safe_load(raw) if raw else {}
    if not isinstance(repo_data, dict):
        return {}
    profile_name = (repo_data.get("review") or {}).get("profile") or ""
    if not profile_name:
        return repo_data
    try:
        profile = load_profile(profile_name)
    except ProfileNotFoundError:
        logger.warning("profile %s not found; using repo config only", profile_name)
        return repo_data
    logger.info("applied team profile %s (repo config wins)", profile_name)
    return merge_configs(profile, repo_data)


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
