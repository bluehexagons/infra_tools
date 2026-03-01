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


logger = get_service_logger('auto_update_uv', 'common', use_syslog=True)


def main() -> int:
    """Update uv to the latest available version for the current user."""
    username = pwd.getpwuid(os.getuid()).pw_name
    home_dir = pwd.getpwnam(username).pw_dir
    uv_path = os.path.join(home_dir, ".local", "bin", "uv")

    if not os.path.exists(uv_path):
        logger.info("uv not found, skipping update")
        return 0

    result = subprocess.run([uv_path, "self", "update"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("uv update failed: %s", result.stderr.strip())
        return 1

    logger.info("uv updated successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
