#!/usr/bin/env python3
"""
Auto-update APT Packages

This script updates all packages from all configured APT repositories using
dist-upgrade. It replaces the traditional unattended-upgrades approach by:

- Not requiring any hardcoded origins or codenames
- Automatically handling all configured repositories
- Supporting release version switches (dist-upgrade resolves dependency changes)

Logs to: /var/log/infra_tools/security/auto_update_apt.log
"""

from __future__ import annotations

import os
import subprocess
import sys

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.notifications import load_notification_configs_from_state, send_notification_safe


# Initialize centralized logger
logger = get_service_logger('auto_update_apt', 'security', use_syslog=True)

# dpkg options to avoid interactive prompts during unattended upgrades
DPKG_OPTIONS = [
    '-o', 'Dpkg::Options::=--force-confdef',
    '-o', 'Dpkg::Options::=--force-confold',
]


def run_apt_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run an apt-get command with non-interactive settings."""
    env = os.environ.copy()
    env['DEBIAN_FRONTEND'] = 'noninteractive'
    cmd = ['apt-get'] + args
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def update_package_lists() -> bool:
    """Run apt-get update to refresh package lists."""
    result = run_apt_command(['update', '-qq'])
    if result.returncode != 0:
        logger.error("apt-get update failed: %s", result.stderr.strip())
        return False
    logger.info("Package lists updated")
    return True


def upgrade_packages() -> tuple[bool, str]:
    """Run apt-get dist-upgrade to upgrade all packages.

    Returns:
        Tuple of (success, output_summary).
    """
    result = run_apt_command(['dist-upgrade', '-y', '-qq'] + DPKG_OPTIONS)
    output = result.stdout.strip()
    if result.returncode != 0:
        logger.error("apt-get dist-upgrade failed: %s", result.stderr.strip())
        return False, result.stderr.strip()
    logger.info("Packages upgraded successfully")
    return True, output


def autoremove_packages() -> None:
    """Run apt-get autoremove to clean up unused packages."""
    result = run_apt_command(['autoremove', '-y', '-qq'])
    if result.returncode != 0:
        logger.warning("apt-get autoremove failed: %s", result.stderr.strip())
    else:
        logger.info("Unused packages removed")


def main() -> int:
    """Main function to update APT packages."""
    logger.info("Starting APT package update")
    notification_configs = load_notification_configs_from_state(logger)

    if not update_package_lists():
        send_notification_safe(
            notification_configs,
            subject="Error: APT update failed",
            job="auto_update_apt",
            status="error",
            message="Failed to update package lists (apt-get update)",
            logger=logger,
        )
        return 1

    success, output = upgrade_packages()
    if not success:
        send_notification_safe(
            notification_configs,
            subject="Error: APT upgrade failed",
            job="auto_update_apt",
            status="error",
            message="Failed to upgrade packages (apt-get dist-upgrade)",
            details=output,
            logger=logger,
        )
        return 1

    autoremove_packages()

    logger.info("APT package update completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
