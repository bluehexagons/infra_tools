#!/usr/bin/env python3
"""
Auto-restart System If Needed

This script checks if a system restart is required (e.g., for kernel updates) and
restarts the system only if no interactive users are logged in.

Logs to: /var/log/infra_tools/common/auto_restart_if_needed.log
"""

from __future__ import annotations
import os
import sys
import subprocess
import shutil

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.notifications import load_notification_configs_from_state, send_notification_safe

# Initialize centralized logger
logger = get_service_logger('auto_restart_if_needed', 'common', use_syslog=True)


def check_restart_required() -> bool:
    """Check if system restart is required."""
    return os.path.exists("/var/run/reboot-required")


def get_logged_in_users() -> list[str]:
    """Get list of logged in users using 'who' command."""
    try:
        result = subprocess.run(
            ["who"],
            capture_output=True,
            text=True,
            check=True
        )
        users: list[str] = [line for line in result.stdout.strip().split('\n') if line]
        return users
    except subprocess.CalledProcessError:
        return []


def check_desktop_sessions() -> bool:
    """Check if any desktop sessions are active."""
    desktop_processes = [
        "Xorg",
        "gnome-session",
        "xfce4-session"
    ]
    
    for process in desktop_processes:
        try:
            # Check for processes owned by regular users (UID 1000+)
            result = subprocess.run(
                ["pgrep", "-u", "1000-", process],
                capture_output=True,
                check=False
            )
            if result.returncode == 0:
                return True
        except Exception:
            continue
    
    return False


def check_rdp_sessions() -> bool:
    """Check if any RDP sessions are active."""
    try:
        result = subprocess.run(
            ["pgrep", "-u", "1000-", "xrdp-sesman"],
            capture_output=True,
            check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def perform_restart(notification_configs) -> int:
    """Perform system restart."""
    logger.info("Restart required and no users logged in, restarting system...")
    send_notification_safe(
        notification_configs,
        subject="Restart required: restarting now",
        job="auto_restart_if_needed",
        status="warning",
        message="A restart is required and no active sessions were detected. Automatic restart is starting now.",
        logger=logger
    )
    
    try:
        shutdown_cmd = shutil.which("shutdown")
        if not shutdown_cmd:
            raise FileNotFoundError("shutdown command not found")
        subprocess.run(
            [shutdown_cmd, "-r", "now", "Automatic restart for system updates"],
            check=True
        )
        return 0
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"✗ Failed to initiate restart: {e}")
        send_notification_safe(
            notification_configs,
            subject="Error: automatic restart failed",
            job="auto_restart_if_needed",
            status="error",
            message=f"Restart required but automatic restart failed: {e}",
            logger=logger
        )
        return 1


def main():
    """Main function to check and perform restart if needed."""
    logger.info("Starting restart check")
    notification_configs = load_notification_configs_from_state(logger)
    
    # Check if restart is required
    if not check_restart_required():
        logger.info("No restart required")
        return 0
    
    # Check for SSH/console sessions
    logged_in_users = get_logged_in_users()
    if logged_in_users:
        logger.info("Users are logged in (SSH/console), skipping restart")
        send_notification_safe(
            notification_configs,
            subject="Restart required: manual restart needed",
            job="auto_restart_if_needed",
            status="warning",
            message="A restart is required, but active SSH/console sessions were detected. Manual restart is required.",
            details="\n".join(logged_in_users),
            logger=logger
        )
        return 0
    
    # Check for desktop sessions
    if check_desktop_sessions():
        logger.info("Desktop session active, skipping restart")
        send_notification_safe(
            notification_configs,
            subject="Restart required: manual restart needed",
            job="auto_restart_if_needed",
            status="warning",
            message="A restart is required, but an active desktop session was detected. Manual restart is required.",
            logger=logger
        )
        return 0
    
    # Check for RDP sessions
    if check_rdp_sessions():
        logger.info("RDP session active, skipping restart")
        send_notification_safe(
            notification_configs,
            subject="Restart required: manual restart needed",
            job="auto_restart_if_needed",
            status="warning",
            message="A restart is required, but an active RDP session was detected. Manual restart is required.",
            logger=logger
        )
        return 0
    
    # No users logged in and restart required, proceed
    return perform_restart(notification_configs)


if __name__ == "__main__":
    sys.exit(main())
