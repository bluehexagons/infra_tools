#!/usr/bin/env python3
"""
Auto-update Node.js

This script updates Node.js to the latest LTS version via nvm.
It also updates global npm and pnpm packages.

Logs to: /var/log/infra_tools/web/auto_update_node.log
"""

from __future__ import annotations

import os
import sys
import subprocess
import pwd
from logging import ERROR

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.logging_utils import log_subprocess_result
from lib.notifications import load_notification_configs_from_state, send_notification_safe

# Initialize centralized logger
logger = get_service_logger('auto_update_node', 'web', use_syslog=True)


def get_nvm_dir() -> str:
    """Get the NVM_DIR path for the current user."""
    # Get the effective user running this process (systemd User= sets this)
    username = pwd.getpwuid(os.getuid()).pw_name
    home_dir = pwd.getpwnam(username).pw_dir
    return os.path.join(home_dir, '.nvm')


def run_nvm_command(cmd: str) -> subprocess.CompletedProcess[str]:
    """Run a command with nvm environment loaded."""
    nvm_dir = get_nvm_dir()
    full_cmd = f'export NVM_DIR="{nvm_dir}" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && {cmd}'
    
    result = subprocess.run(
        full_cmd,
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True
    )
    return result


def get_current_lts_version() -> str:
    """Get the latest LTS version available."""
    result = run_nvm_command("nvm version-remote --lts")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_current_version() -> str:
    """Get the currently installed default version."""
    result = run_nvm_command("nvm version default")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def install_lts_version():
    """Install the latest LTS version."""
    result = run_nvm_command("nvm install --lts")
    return log_subprocess_result(logger, "Installed latest Node.js LTS", result, failure_level=ERROR)


def update_global_packages():
    """Update global npm and pnpm packages."""
    result = run_nvm_command("npm install -g npm@latest")
    log_subprocess_result(logger, "Updated npm", result)
    
    result = run_nvm_command("npm install -g pnpm")
    log_subprocess_result(logger, "Updated pnpm", result)


def update_symlinks():
    """
    Update symlinks in user's local bin directory.
    
    Note: For user installations, symlinks are not needed as nvm
    adds the node bin directory to PATH via bashrc.
    """
    # User installations don't need global symlinks
    # The user's PATH includes the nvm bin directory
    pass


def fix_permissions():
    """
    Fix permissions on nvm directory.
    
    Note: For user installations, permissions are already correct
    since nvm is installed in the user's home directory.
    """
    # User installations already have correct permissions
    pass


def main():
    """Main function to update Node.js."""
    logger.info("Starting Node.js update check")
    
    nvm_dir = get_nvm_dir()
    
    # Load notification configs from saved machine state
    notification_configs = load_notification_configs_from_state(logger)
    
    if not os.path.exists(nvm_dir):
        logger.error(f"✗ nvm not found at {nvm_dir}")
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message=f"nvm not found at {nvm_dir}",
            logger=logger
        )
        return 1
    
    current_lts = get_current_lts_version()
    current_version = get_current_version()
    
    if not current_lts:
        logger.error("✗ Failed to get latest LTS version")
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message="Failed to get latest LTS version",
            logger=logger
        )
        return 1
    
    if not current_version:
        logger.error("✗ Failed to get current version")
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message="Failed to get current Node.js version",
            logger=logger
        )
        return 1
    
    if current_version == current_lts:
        logger.info(f"Node.js already at latest LTS version: {current_lts}")
        return 0
    
    logger.info(f"Updating Node.js from {current_version} to {current_lts}")
    
    if not install_lts_version():
        logger.error("✗ Node.js update failed")
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message=f"Failed to update from {current_version} to {current_lts}",
            logger=logger
        )
        return 1
    
    update_global_packages()
    update_symlinks()
    fix_permissions()
    
    logger.info(f"✓ Node.js updated successfully to {current_lts}")
    
    send_notification_safe(
        notification_configs,
        subject="Success: Node.js updated",
        job="auto_update_node",
        status="good",
        message=f"Updated from {current_version} to {current_lts}",
        logger=logger
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
