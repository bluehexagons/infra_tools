#!/usr/bin/env python3
"""XRDP Dynamic Resolution Handler

Monitors for resolution changes and updates desktop environment accordingly.
This script helps desktop environments respond to RDP window resize events.

For XFCE and Cinnamon, this is mostly automatic, but ensures consistency.
For i3 and other tiling WMs, this ensures proper screen reconfiguration.

Logs to: syslog with xrdp-resize tag
"""

from __future__ import annotations

import os
import sys
import subprocess
import select
import time

# Add lib directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from desktop.service_tools.xrdp_utils import (
    get_rdp_output_name,
    get_current_resolution,
    is_resolution_valid,
    reset_resolution_to_auto,
    resolution_lock
)

# Initialize centralized logger
logger = get_service_logger('xrdp_resize_handler', 'desktop', use_syslog=True)


def handle_resize(desktop_session: str) -> None:
    """Handle resolution changes for the current desktop environment.
    
    Args:
        desktop_session: Name of the desktop session (xfce, cinnamon, i3, etc.)
    """
    resolution = get_current_resolution()
    if resolution:
        logger.info(f"Detected resolution: {resolution}")
    
    try:
        if desktop_session == 'xfce':
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
            logger.info("XFCE desktop refreshed")
            
        elif desktop_session == 'cinnamon':
            subprocess.run(
                ['dbus-send', '--session', '--dest=org.Cinnamon',
                 '--type=method_call', '/org/Cinnamon',
                 'org.Cinnamon.RestartCinnamon'],
                capture_output=True,
                timeout=5,
                check=False
            )
            logger.info("Cinnamon desktop refresh requested")
            
        elif desktop_session == 'i3':
            # i3 needs explicit restart to recalculate tiling layouts
            subprocess.run(
                ['i3-msg', 'restart'],
                capture_output=True,
                timeout=5,
                check=False
            )
            logger.info("i3 window manager restarted")
            
        else:
            # Generic approach for other window managers
            rdp_output = get_rdp_output_name()
            if reset_resolution_to_auto(rdp_output):
                logger.info(f"Generic resolution refresh applied to output {rdp_output}")
            else:
                logger.warning(f"Failed to refresh resolution for output {rdp_output}")
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout while refreshing {desktop_session} desktop")
    except Exception as e:
        logger.warning(f"Failed to refresh desktop: {e}")


def monitor_randr_events(desktop_session: str) -> None:
    """Monitor for RANDR screen change events using xev.
    
    Args:
        desktop_session: Name of the desktop session
    """
    logger.info(f"Starting resolution monitor for session: {desktop_session}")
    
    # Verify xev is available
    try:
        subprocess.run(
            ['which', 'xev'],
            capture_output=True,
            timeout=2,
            check=True
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        logger.error("xev command not found - cannot monitor resolution changes")
        logger.info("Install x11-utils package for dynamic resolution support")
        return
    
    proc = None
    try:
        # Start xev to monitor root window events
        proc = subprocess.Popen(
            ['xev', '-root', '-event', 'randr'],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )
        
        # Initial resolution setup after brief delay
        time.sleep(2)
        
        # First check if we're in a bad state (invalid dimensions)
        current_res = get_current_resolution()
        if not is_resolution_valid(current_res):
            logger.warning(f"Invalid resolution detected: {current_res}, attempting reset")
            
            with resolution_lock("resize-startup", timeout=5.0) as acquired:
                if acquired:
                    rdp_output = get_rdp_output_name()
                    if reset_resolution_to_auto(rdp_output):
                        logger.info("Resolution reset successful")
                    else:
                        logger.error("Resolution reset failed")
                    time.sleep(1)
                else:
                    logger.warning("Could not acquire lock for resolution reset, skipping")
        
        handle_resize(desktop_session)
        
        # Monitor for events
        while True:
            if proc.stdout:
                # Use select to avoid blocking indefinitely
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                if ready:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    
                    if 'RRScreenChangeNotify' in line:
                        logger.info("Screen change event detected")
                        
                        # Acquire lock before handling resize
                        with resolution_lock("resize-event", timeout=2.0) as acquired:
                            if acquired:
                                # Brief delay to let X server settle
                                time.sleep(0.5)
                                handle_resize(desktop_session)
                            else:
                                logger.info("Resize locked by another process, skipping")
            
            if proc.poll() is not None:
                break
                
    except KeyboardInterrupt:
        logger.info("Resolution monitor stopped by user")
    except Exception as e:
        logger.error(f"Error monitoring RANDR events: {e}")
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> int:
    """Main entry point."""
    # Detect desktop session from environment
    desktop_session = os.environ.get('DESKTOP_SESSION', '').lower()
    
    # Map common session names to our handler names
    if 'xfce' in desktop_session:
        desktop_session = 'xfce'
    elif 'cinnamon' in desktop_session:
        desktop_session = 'cinnamon'
    elif 'i3' in desktop_session or desktop_session == 'i3':
        desktop_session = 'i3'
    
    logger.info(f"Resolution handler started for user: {os.environ.get('USER', 'unknown')}")
    logger.info(f"Desktop session: {desktop_session or 'generic'}")
    
    monitor_randr_events(desktop_session)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
