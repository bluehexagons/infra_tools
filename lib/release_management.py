"""Shared helpers for GitHub release-backed service installs."""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable, Mapping
from typing import Any

from lib.remote_utils import run
from lib.update_policy import order_preferred_github_releases


def detect_release_arch() -> str:
    """Return the GitHub release architecture suffix for this machine."""
    result = run("uname -m", capture_output=True)
    arch = result.stdout.strip() if result.stdout else "x86_64"
    if arch in ("aarch64", "arm64"):
        return "arm64"
    return "amd64"


def fetch_github_releases(repo: str, *, per_page: int = 20) -> list[Mapping[str, Any]]:
    """Fetch recent GitHub releases for a repository."""
    api_url = f"https://api.github.com/repos/{repo}/releases?per_page={per_page}"
    result = run(
        f"curl -sf {shlex.quote(api_url)}",
        capture_output=True,
        display_cmd=f"curl -sf https://api.github.com/repos/{repo}/releases?per_page={per_page}",
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"Failed to fetch {repo} release data from GitHub")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse {repo} release data: {exc}") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected {repo} release response payload")
    return payload


def select_preferred_github_release_asset(
    releases: list[Mapping[str, Any]],
    *,
    asset_matches: Callable[[str, str], bool],
    missing_asset_description: str,
) -> tuple[str, str]:
    """Return the preferred release tag and asset URL matching the selector."""
    for release in order_preferred_github_releases(releases):
        tag_name = release.get("tag_name")
        if not isinstance(tag_name, str) or not tag_name:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_name = asset.get("name")
            download_url = asset.get("browser_download_url")
            if (
                isinstance(asset_name, str)
                and isinstance(download_url, str)
                and asset_matches(tag_name, asset_name)
            ):
                return tag_name, download_url
    raise RuntimeError(missing_asset_description)


def fetch_preferred_github_release_asset(
    repo: str,
    *,
    asset_matches: Callable[[str, str], bool],
    missing_asset_description: str,
    per_page: int = 20,
) -> tuple[str, str]:
    """Fetch and select the preferred GitHub release asset for a repository."""
    releases = fetch_github_releases(repo, per_page=per_page)
    return select_preferred_github_release_asset(
        releases,
        asset_matches=asset_matches,
        missing_asset_description=missing_asset_description,
    )


def load_json_state(
    path: str,
    *,
    read_error_label: str,
    invalid_state_message: str,
) -> dict[str, Any]:
    """Load a JSON object state file, returning an empty mapping when unavailable."""
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ Warning: Failed to read {read_error_label}: {exc}")
        return {}
    if not isinstance(payload, dict):
        print(f"  ⚠ Warning: {invalid_state_message}")
        return {}
    return payload


def write_json_state(path: str, payload: Mapping[str, Any], *, mode: int | None = None) -> None:
    """Persist a JSON state mapping."""
    state_dir = os.path.dirname(path)
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2, sort_keys=True)
        file_obj.write("\n")
    if mode is not None:
        os.chmod(path, mode)
