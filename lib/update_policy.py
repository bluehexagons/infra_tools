"""Shared policy helpers for automatic update services."""

from __future__ import annotations

import os
from collections.abc import Mapping


ECOSYSTEM_AUTO_UPGRADE_ENV = "INFRA_TOOLS_ECOSYSTEM_AUTO_UPGRADE"
NODE_LATEST_AUTO_UPDATE_ENV = "INFRA_TOOLS_NODE_LATEST_AUTO_UPDATE"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_flag_enabled(
    name: str,
    *,
    default: bool = False,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether an environment flag is enabled."""
    value = (env or os.environ).get(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def ecosystem_auto_upgrade_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether global npm/gem/uv-tool upgrades are allowed."""
    return env_flag_enabled(ECOSYSTEM_AUTO_UPGRADE_ENV, env=env)


def node_latest_auto_update_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether Node.js latest-track auto-updates are allowed."""
    return env_flag_enabled(NODE_LATEST_AUTO_UPDATE_ENV, env=env)
