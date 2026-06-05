"""Maintenance helpers for APT source files."""

from __future__ import annotations

import os

from lib.validation import validate_filesystem_path


APT_SOURCES_DIR = "/etc/apt/sources.list.d"
VIVALDI_LIST_FILE = "vivaldi.list"
VIVALDI_SOURCES_FILE = "vivaldi.sources"
DISABLED_SUFFIX = ".disabled-by-infra-tools"


def _contains_vivaldi_repository(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file_obj:
            content = file_obj.read().lower()
    except OSError:
        return False
    return "repo.vivaldi.com" in content and "vivaldi" in content


def _next_disabled_path(path: str) -> str:
    candidate = f"{path}{DISABLED_SUFFIX}"
    if not os.path.lexists(candidate):
        return candidate
    for index in range(1, 100):
        candidate = f"{path}{DISABLED_SUFFIX}.{index}"
        if not os.path.lexists(candidate):
            return candidate
    raise FileExistsError(f"No available disabled path for {path}")


def disable_duplicate_vivaldi_source(sources_dir: str = APT_SOURCES_DIR) -> str | None:
    """Disable duplicate Vivaldi APT source files.

    Some upgraded systems have both the legacy ``vivaldi.list`` and modern
    Deb822 ``vivaldi.sources`` files. APT treats them as separate sources and
    warns that the same targets are configured multiple times. Prefer the
    modern ``.sources`` file and rename the legacy ``.list`` file when both are
    present and both clearly reference Vivaldi's repository.
    """
    validate_filesystem_path(sources_dir, must_exist=False)
    if not os.path.isdir(sources_dir):
        return None

    legacy_list = os.path.join(sources_dir, VIVALDI_LIST_FILE)
    modern_sources = os.path.join(sources_dir, VIVALDI_SOURCES_FILE)
    if not os.path.isfile(legacy_list) or not os.path.isfile(modern_sources):
        return None
    if not _contains_vivaldi_repository(legacy_list):
        return None
    if not _contains_vivaldi_repository(modern_sources):
        return None

    disabled_path = _next_disabled_path(legacy_list)
    os.rename(legacy_list, disabled_path)
    return disabled_path
