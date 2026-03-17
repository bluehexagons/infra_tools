#!/usr/bin/env python3
"""
Auto-update Node.js

This script updates Node.js via nvm, following the current default alias
track (LTS or latest). It also updates global npm packages.

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
from lib.types import MaybeStr

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


def get_latest_version() -> str:
    """Get the latest non-LTS stable version available."""
    result = run_nvm_command("nvm version-remote node")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_current_version() -> str:
    """Get the currently installed default version."""
    result = run_nvm_command("nvm version default")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_default_alias() -> str:
    """Get the nvm default alias definition."""
    result = run_nvm_command("nvm alias default")
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def determine_update_track(alias_output: str) -> str:
    """Determine whether the current default alias tracks LTS or latest."""
    alias_lower = alias_output.lower()
    if "->" in alias_output:
        alias_target = alias_output.split("->", 1)[1].strip().split()[0].lower()
        if alias_target == "node":
            return "latest"
        if alias_target.startswith("lts"):
            return "lts"

    if "lts" in alias_lower:
        return "lts"
    if "default -> node" in alias_lower:
        return "latest"
    return "lts"


def install_target_version(update_track: str) -> bool:
    """Install the latest Node.js version for the selected track."""
    install_arg = "node" if update_track == "latest" else "--lts"
    result = run_nvm_command(f"nvm install {install_arg}")
    action = "Installed latest Node.js version" if update_track == "latest" else "Installed latest Node.js LTS"
    return log_subprocess_result(logger, action, result, failure_level=ERROR)


def update_global_packages() -> tuple[bool, MaybeStr]:
    """Update npm itself and global npm packages."""
    commands = (
        ("Updated npm", "npm install -g npm@latest"),
        ("Updated global npm packages", "npm update -g"),
        ("Updated pnpm", "npm install -g pnpm"),
    )
    failures: list[str] = []

    for action, command in commands:
        result = run_nvm_command(command)
        if not log_subprocess_result(logger, action, result):
            details = result.stderr.strip() or result.stdout.strip() or command
            failures.append(f"{action}: {details}")

    if failures:
        return False, "\n".join(failures)
    return True, None


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
    latest_version = get_latest_version()
    current_version = get_current_version()
    update_track = determine_update_track(get_default_alias())
    target_version = latest_version if update_track == "latest" else current_lts
    track_label = "latest" if update_track == "latest" else "LTS"
    
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
    
    if update_track == "latest" and not latest_version:
        logger.error("✗ Failed to get latest Node.js version")
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message="Failed to get latest Node.js version",
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
    
    if current_version == target_version:
        logger.info(f"Node.js already at latest {track_label} version: {target_version}")
    else:
        logger.info(f"Updating Node.js ({track_label}) from {current_version} to {target_version}")
        
        if not install_target_version(update_track):
            logger.error("✗ Node.js update failed")
            send_notification_safe(
                notification_configs,
                subject="Error: Node.js update failed",
                job="auto_update_node",
                status="error",
                message=f"Failed to update from {current_version} to {target_version}",
                logger=logger
            )
            return 1

    packages_updated, package_error = update_global_packages()
    if not packages_updated:
        logger.error("✗ Node.js global package update failed")
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message="Failed to update global Node.js packages",
            details=package_error,
            logger=logger
        )
        return 1

    update_symlinks()
    fix_permissions()
    
    logger.info(f"✓ Node.js update tasks completed successfully for {target_version}")
    
    send_notification_safe(
        notification_configs,
        subject="Success: Node.js updated",
        job="auto_update_node",
        status="good",
        message=f"Node.js {track_label} track checked (current: {current_version}, target: {target_version}) and global packages were updated",
        logger=logger
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
