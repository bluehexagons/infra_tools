#!/usr/bin/env python3
"""XRDP Session Reconnection Handler

This script runs when reconnecting to an existing XRDP session.
It fixes the "black screen" issue caused by invalid display dimensions (0x0).

The script:
- Detects the actual RDP output name (rdp0, rdp1, etc.)
- Resets display resolution to fix invalid dimensions
- Refreshes desktop environment components

Logs to: syslog with xrdp-reconnect tag
"""

from __future__ import annotations

import os
import sys
import subprocess
import time

# Add lib directory to path for imports
# Resolve symlinks to get the actual script location
script_path = os.path.realpath(__file__)
sys.path.insert(0, os.path.join(os.path.dirname(script_path), '../..'))

from lib.logging_utils import get_service_logger
from desktop.service_tools.xrdp_utils import (
    get_rdp_output_name,
    get_current_resolution,
    is_resolution_valid,
    reset_resolution_to_auto,
    set_resolution_mode,
    get_fallback_resolutions,
    resolution_lock
)

# Initialize centralized logger
logger = get_service_logger('xrdp_reconnect_handler', 'desktop', use_syslog=True)


def reset_display_resolution(rdp_output: str) -> bool:
    """Reset display resolution to fix invalid dimensions.
    
    Args:
        rdp_output: RDP output name (e.g., "rdp0")
        
    Returns:
        True if successful, False otherwise
    """
    current_res = get_current_resolution()
    
    if is_resolution_valid(current_res):
        logger.info(f"Current resolution: {current_res}")
        # Force auto-configure to ensure proper mode
        if reset_resolution_to_auto(rdp_output):
            new_res = get_current_resolution()
            logger.info(f"Resolution after reset: {new_res}")
            return True
        else:
            logger.warning("xrandr --auto failed")
            return False
    else:
        logger.warning(f"Invalid resolution detected ({current_res}), forcing default")
        
        # Try common resolutions in order
        for res in get_fallback_resolutions():
            if set_resolution_mode(rdp_output, res):
                logger.info(f"Successfully set fallback resolution: {res}")
                return True
        
        # Last resort: try auto
        if reset_resolution_to_auto(rdp_output):
            logger.info("Applied xrandr --auto as last resort")
            return True
        else:
            logger.error("All resolution reset attempts failed")
            return False


def refresh_desktop_environment() -> None:
    """Refresh desktop environment components based on session type."""
    desktop_session = os.environ.get('DESKTOP_SESSION', '').lower()
    
    try:
        if 'xfce' in desktop_session:
            logger.info("Refreshing XFCE desktop")
            subprocess.run(
                ['xfdesktop', '--reload'],
                capture_output=True,
                timeout=5,
                check=False
            )
            subprocess.run(
                ['xfce4-panel', '-r'],
                capture_output=True,
                timeout=5,
                check=False
            )
            
        elif 'cinnamon' in desktop_session:
            logger.info("Refreshing Cinnamon desktop")
            subprocess.run(
                ['dbus-send', '--session', '--dest=org.Cinnamon',
                 '--type=method_call', '/org/Cinnamon',
                 'org.Cinnamon.RestartCinnamon'],
                capture_output=True,
                timeout=5,
                check=False
            )
            
        elif 'i3' in desktop_session or desktop_session == 'i3':
            logger.info("Restarting i3 window manager")
            subprocess.run(
                ['i3-msg', 'restart'],
                capture_output=True,
                timeout=5,
                check=False
            )
        else:
            logger.info(f"Generic refresh for session: {desktop_session or 'unknown'}")
            
    except Exception as e:
        logger.warning(f"Failed to refresh desktop environment: {e}")


def main() -> int:
    """Main entry point."""
    user = os.environ.get('USER', 'unknown')
    display = os.environ.get('DISPLAY', 'unknown')
    
    logger.info(f"Reconnection script starting for user {user} on display {display}")
    
    # Give X server a moment to stabilize
    time.sleep(1)
    
    # Detect RDP output name
    rdp_output = get_rdp_output_name()
    logger.info(f"Detected RDP output: {rdp_output}")
    
    # Acquire lock to prevent race with resize handler
    with resolution_lock("reconnect", timeout=10.0) as acquired:
        if not acquired:
            logger.warning("Could not acquire resolution lock, another process is active")
            # Still try to continue, but without lock protection
        
        # Reset display resolution
        if reset_display_resolution(rdp_output):
            logger.info("Display resolution reset successfully")
        else:
            logger.error("Failed to reset display resolution")
            # Don't return error - allow session to continue even if resolution reset failed
    
    # Give resolution change time to settle before refreshing DE
    time.sleep(0.5)
    
    # Refresh desktop environment components
    refresh_desktop_environment()
    
    logger.info("Reconnection script completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
