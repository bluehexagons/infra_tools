#!/usr/bin/env python3
"""xRDP Session Cleanup Script

Ensures xRDP-related processes are terminated when RDP session ends.
Addresses issue of orphaned xrdp-sesexec processes that prevent re-login.

This script is called by xrdp's EndSessionCommand in sesman.ini.

Logs to: /var/log/infra_tools/desktop/xrdp_session_cleanup.log
"""

from __future__ import annotations

import os
import sys
import subprocess

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger

# Initialize centralized logger
logger = get_service_logger('xrdp_session_cleanup', 'desktop', use_syslog=True)


def kill_processes(username: str, pattern: str, exact: bool = False) -> None:
    """Kill processes matching pattern for the specified user.
    
    Args:
        username: Username whose processes to kill
        pattern: Process name or pattern to match
        exact: If True, match exact process name only
    """
    try:
        if exact:
            # Exact match on process name
            subprocess.run(
                ["pkill", "-u", username, "-x", pattern],
                capture_output=True,
                check=False
            )
        else:
            # Pattern match in command line
            subprocess.run(
                ["pkill", "-u", username, "-f", pattern],
                capture_output=True,
                check=False
            )
    except Exception:
        # Ignore errors - process might not exist
        pass


def main() -> int:
    """Main cleanup routine."""
    # Get username from environment or first argument
    username = os.environ.get("PAM_USER") or os.environ.get("USER")
    if not username and len(sys.argv) > 1:
        username = sys.argv[1]
    
    if not username:
        error_msg = "No user specified for cleanup"
        logger.error(error_msg)
        return 1
    
    logger.info(f"Starting session cleanup for user: {username}")
    
    # Kill PulseAudio processes spawned by this xRDP session
    kill_processes(username, "pulseaudio", exact=True)
    
    # Terminate xRDP-specific processes only (not all user processes)
    # This prevents disrupting other active sessions (SSH, other RDP, etc.)
    kill_processes(username, "xrdp-sesexec", exact=True)
    kill_processes(username, "xrdp-sesman", exact=True)
    kill_processes(username, "xrdp-chansrv", exact=True)
    
    # Kill session-specific desktop processes
    kill_processes(username, "xfce4-session", exact=False)
    kill_processes(username, "cinnamon-session", exact=False)
    kill_processes(username, "i3", exact=True)
    
    logger.info(f"Session cleanup completed for user: {username}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
