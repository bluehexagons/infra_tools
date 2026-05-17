#!/usr/bin/env python3
"""
Auto-update Node.js

This script updates Node.js via nvm on the LTS track by default. Global npm
package upgrades and latest-track Node.js upgrades are opt-in by policy.

Logs to: /var/log/infra_tools/web/auto_update_node.log
"""

from __future__ import annotations

import os
import shlex
import sys
import subprocess
import pwd
from logging import ERROR, WARNING

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.logging_utils import log_event
from lib.logging_utils import log_subprocess_result
from lib.notifications import load_notification_configs_from_state, send_notification_safe
from lib.types import MaybeStr
from lib.update_policy import (
    ECOSYSTEM_AUTO_UPGRADE_ENV,
    NODE_LATEST_AUTO_UPDATE_ENV,
    ecosystem_auto_upgrade_enabled,
    node_latest_auto_update_enabled,
)

# Initialize centralized logger
logger = get_service_logger('auto_update_node', 'web', use_syslog=True)


def get_nvm_dir() -> str:
    """Get the NVM_DIR path for the current user."""
    # Get the effective user running this process (systemd User= sets this)
    username = pwd.getpwuid(os.getuid()).pw_name
    home_dir = pwd.getpwnam(username).pw_dir
    return os.path.join(home_dir, '.nvm')


def run_nvm_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command with nvm environment loaded."""
    nvm_dir = get_nvm_dir()
    full_cmd = (
        f'export NVM_DIR={shlex.quote(nvm_dir)} && '
        '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && '
        f'{shlex.join(args)}'
    )

    result = subprocess.run(
        ["/bin/bash", "-lc", full_cmd],
        capture_output=True,
        text=True,
    )
    return result


def get_current_lts_version() -> str:
    """Get the latest LTS version available."""
    result = run_nvm_command(["nvm", "version-remote", "--lts"])
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_latest_version() -> str:
    """Get the latest non-LTS stable version available."""
    result = run_nvm_command(["nvm", "version-remote", "node"])
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_current_version() -> str:
    """Get the currently installed default version."""
    result = run_nvm_command(["nvm", "version", "default"])
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def get_default_alias() -> str:
    """Get the nvm default alias definition."""
    result = run_nvm_command(["nvm", "alias", "default"])
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
    result = run_nvm_command(["nvm", "install", install_arg])
    action = "Installed latest Node.js version" if update_track == "latest" else "Installed latest Node.js LTS"
    return log_subprocess_result(logger, action, result, failure_level=ERROR)


def update_global_packages() -> tuple[bool, MaybeStr]:
    """Update npm itself and global npm packages."""
    if not ecosystem_auto_upgrade_enabled():
        log_event(
            logger,
            "Node.js global package auto-upgrades disabled by policy",
            env_var=ECOSYSTEM_AUTO_UPGRADE_ENV,
        )
        return True, None

    commands = (
        ("Updated npm", "npm install -g npm@latest"),
        ("Updated global npm packages", "npm update -g"),
        ("Updated pnpm", "npm install -g pnpm"),
    )
    failures: list[str] = []

    for action, command in commands:
        result = run_nvm_command(shlex.split(command))
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
    log_event(logger, "Starting Node.js update check")
    
    nvm_dir = get_nvm_dir()
    
    # Load notification configs from saved machine state
    notification_configs = load_notification_configs_from_state(logger)
    
    if not os.path.exists(nvm_dir):
        log_event(logger, "nvm directory not found", level=ERROR, nvm_dir=nvm_dir)
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
    track_label = "latest" if update_track == "latest" else "LTS"
    latest_policy_skipped = update_track == "latest" and not node_latest_auto_update_enabled()
    target_version = current_version if latest_policy_skipped else (
        latest_version if update_track == "latest" else current_lts
    )
    
    if update_track != "latest" and not current_lts:
        log_event(logger, "Failed to get latest LTS version", level=ERROR)
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message="Failed to get latest LTS version",
            logger=logger
        )
        return 1
    
    if update_track == "latest" and not latest_policy_skipped and not latest_version:
        log_event(logger, "Failed to get latest Node.js version", level=ERROR, update_track=update_track)
        send_notification_safe(
            notification_configs,
            subject="Error: Node.js update failed",
            job="auto_update_node",
            status="error",
            message="Failed to get latest Node.js version",
            logger=logger
        )
        return 1

    if latest_policy_skipped:
        log_event(
            logger,
            "Node.js latest-track auto-update disabled by policy",
            level=WARNING,
            current_version=current_version,
            env_var=NODE_LATEST_AUTO_UPDATE_ENV,
        )

    if not current_version:
        log_event(logger, "Failed to get current Node.js version", level=ERROR, update_track=update_track)
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
        log_event(
            logger,
            "Node.js already up to date",
            current_version=current_version,
            target_version=target_version,
            update_track=track_label,
        )
    else:
        log_event(
            logger,
            "Updating Node.js",
            current_version=current_version,
            target_version=target_version,
            update_track=track_label,
        )
        
        if not install_target_version(update_track):
            log_event(
                logger,
                "Node.js update failed",
                level=ERROR,
                current_version=current_version,
                target_version=target_version,
                update_track=track_label,
            )
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
        log_event(
            logger,
            "Node.js global package update failed",
            level=ERROR,
            current_version=current_version,
            target_version=target_version,
            update_track=track_label,
        )
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
    
    # Re-read the current version after any successful install so notifications reflect
    # the actual installed Node.js version rather than the pre-update version.
    post_update_version = get_current_version() or current_version
    
    log_event(
        logger,
        "Node.js update tasks completed successfully",
        current_version=post_update_version,
        target_version=target_version,
        update_track=track_label,
    )
    
    send_notification_safe(
        notification_configs,
        subject="Success: Node.js updated",
        job="auto_update_node",
        status="good",
        message=(
            f"Node.js {track_label} track checked (current: {post_update_version}, target: {target_version}); "
            f"global package auto-upgrades "
            f"{'enabled' if ecosystem_auto_upgrade_enabled() else 'skipped by policy'}"
        ),
        logger=logger
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
