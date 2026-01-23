#!/usr/bin/env python3
"""xRDP Session Cleanup Script

Ensures xRDP-related processes are terminated when RDP session ends.
Addresses issue of orphaned xrdp-sesexec processes that prevent re-login.

This script is called by xrdp's EndSessionCommand in sesman.ini.
"""

from __future__ import annotations

import os
import sys
import subprocess
import syslog


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
    # Initialize syslog once
    syslog.openlog("xrdp-cleanup", syslog.LOG_PID, syslog.LOG_USER)
    
    # Get username from environment or first argument
    username = os.environ.get("PAM_USER") or os.environ.get("USER")
    if not username and len(sys.argv) > 1:
        username = sys.argv[1]
    
    if not username:
        syslog.syslog(syslog.LOG_ERR, "ERROR: No user specified for cleanup")
        syslog.closelog()
        return 1
    
    syslog.syslog(syslog.LOG_INFO, f"Starting session cleanup for user: {username}")
    
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
    
    syslog.syslog(syslog.LOG_INFO, f"Session cleanup completed for user: {username}")
    syslog.closelog()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
