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

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger

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


def perform_restart():
    """Perform system restart."""
    logger.info("Restart required and no users logged in, restarting system...")
    
    try:
        subprocess.run(
            ["/sbin/shutdown", "-r", "now", "Automatic restart for system updates"],
            check=True
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ Failed to initiate restart: {e}")
        sys.exit(1)


def main():
    """Main function to check and perform restart if needed."""
    logger.info("Starting restart check")
    
    # Check if restart is required
    if not check_restart_required():
        logger.info("No restart required")
        return 0
    
    # Check for SSH/console sessions
    logged_in_users = get_logged_in_users()
    if logged_in_users:
        logger.info("Users are logged in (SSH/console), skipping restart")
        return 0
    
    # Check for desktop sessions
    if check_desktop_sessions():
        logger.info("Desktop session active, skipping restart")
        return 0
    
    # Check for RDP sessions
    if check_rdp_sessions():
        logger.info("RDP session active, skipping restart")
        return 0
    
    # No users logged in and restart required, proceed
    perform_restart()
    return 0


if __name__ == "__main__":
    sys.exit(main())
