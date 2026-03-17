#!/usr/bin/env python3
"""
Auto-update uv package manager.
"""

from __future__ import annotations

import os
import pwd
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.notifications import load_notification_configs_from_state, send_notification_safe


logger = get_service_logger('auto_update_uv', 'common', use_syslog=True)


def main() -> int:
    """Update uv to the latest available version for the current user."""
    pw_entry = pwd.getpwuid(os.getuid())
    home_dir = pw_entry.pw_dir
    uv_path = os.path.join(home_dir, ".local", "bin", "uv")
    notification_configs = load_notification_configs_from_state(logger)

    if not os.path.exists(uv_path):
        logger.info("uv not found, skipping update")
        return 0

    result = subprocess.run([uv_path, "self", "update"], capture_output=True, text=True)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "uv self update failed"
        logger.error("uv update failed: %s", details)
        send_notification_safe(
            notification_configs,
            subject="Error: uv update failed",
            job="auto_update_uv",
            status="error",
            message="Failed to update uv",
            details=details,
            logger=logger,
        )
        return 1

    result = subprocess.run([uv_path, "tool", "upgrade", "--all"], capture_output=True, text=True)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "uv tool upgrade failed"
        logger.error("uv tool upgrade failed: %s", details)
        send_notification_safe(
            notification_configs,
            subject="Error: uv tool upgrade failed",
            job="auto_update_uv",
            status="error",
            message="Failed to upgrade one or more uv-managed tools",
            details=details,
            logger=logger,
        )
        return 1

    logger.info("uv and uv-managed tools updated successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
