#!/usr/bin/env python3
"""
Auto-update global Ruby gems.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.notifications import load_notification_configs_from_state, send_notification_safe


logger = get_service_logger('auto_update_ruby', 'common', use_syslog=True)


def run_gem_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gem command and capture output."""
    return subprocess.run(["gem"] + args, capture_output=True, text=True)


def gem_installed(gem_name: str) -> bool:
    """Check whether a gem is installed globally."""
    result = run_gem_command(["list", "-i", gem_name])
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def update_gem(gem_name: str) -> tuple[bool, str]:
    """Update an installed gem."""
    result = run_gem_command(["update", gem_name])
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or f"Failed to update {gem_name}"
        logger.error("gem update %s failed: %s", gem_name, details)
        return False, details

    logger.info("%s updated successfully", gem_name)
    return True, result.stdout.strip()


def main() -> int:
    """Update commonly used global Ruby gems when present."""
    gem_path = shutil.which("gem")
    if not gem_path:
        logger.info("gem not found, skipping update")
        return 0

    logger.info("Starting Ruby gem update check")
    notification_configs = load_notification_configs_from_state(logger)

    failed_updates: list[str] = []
    updated_gems: list[str] = []

    for gem_name in ("bundler", "rails"):
        if not gem_installed(gem_name):
            logger.info("%s not installed, skipping", gem_name)
            continue

        success, details = update_gem(gem_name)
        if not success:
            failed_updates.append(f"{gem_name}: {details}")
        else:
            updated_gems.append(gem_name)

    if failed_updates:
        send_notification_safe(
            notification_configs,
            subject="Error: Ruby gem update failed",
            job="auto_update_ruby",
            status="error",
            message="Failed to update one or more global Ruby gems",
            details="\n".join(failed_updates),
            logger=logger,
        )
        return 1

    if updated_gems:
        logger.info("Updated Ruby gems: %s", ", ".join(updated_gems))
    else:
        logger.info("No managed global Ruby gems installed, nothing to update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
