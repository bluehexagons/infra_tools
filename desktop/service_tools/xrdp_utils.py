#!/usr/bin/env python3
"""XRDP Utility Functions

Shared utilities for XRDP resolution handling and session management.
Used by both xrdp_resize_handler.py and xrdp_reconnect_handler.py.
"""

from __future__ import annotations

import os
import subprocess
import re
import fcntl
import time
from contextlib import contextmanager
from typing import Generator

# Lock file directory
LOCK_DIR = "/tmp/xrdp-locks"


def ensure_lock_dir() -> None:
    """Ensure lock directory exists with proper permissions."""
    try:
        os.makedirs(LOCK_DIR, mode=0o755, exist_ok=True)
    except Exception:
        # If we can't create /tmp/xrdp-locks, fall back to /tmp
        pass


def get_rdp_output_name() -> str:
    """Get the actual RDP output name from xrandr.
    
    Returns:
        Output name like "rdp0" or "default" as fallback
    """
    try:
        result = subprocess.run(
            ['xrandr', '--current'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            # Look for rdp outputs (rdp0, rdp1, etc.)
            match = re.search(r'^(rdp\d+)', result.stdout, re.MULTILINE)
            if match:
                return match.group(1)
    except Exception:
        pass
    return "default"


def get_current_resolution() -> str | None:
    """Get current screen resolution using xrandr.
    
    Returns:
        Resolution string like "1920x1080" or None if unable to detect
    """
    try:
        result = subprocess.run(
            ['xrandr', '--current'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            match = re.search(r'(\d+x\d+)', result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


@contextmanager
def resolution_lock(operation: str, timeout: float = 5.0) -> Generator[bool, None, None]:
    """Context manager for resolution operation locking.
    
    Prevents race conditions between resize and reconnect handlers.
    
    Args:
        operation: Name of operation (e.g., "resize", "reconnect")
        timeout: Maximum time to wait for lock in seconds
        
    Yields:
        True if lock acquired, False if timeout
        
    Example:
        with resolution_lock("reconnect") as acquired:
            if acquired:
                # Perform resolution changes
                pass
            else:
                # Lock timeout, skip operation
                pass
    """
    ensure_lock_dir()
    
    display = os.environ.get('DISPLAY', ':0')
    # Sanitize display name for filesystem
    safe_display = display.replace(':', '_').replace('.', '_')
    lock_file = os.path.join(LOCK_DIR, f"xrdp-resolution-{safe_display}.lock")
    
    fd = None
    acquired = False
    
    try:
        # Open/create lock file
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o644)
        
        # Try to acquire lock with timeout
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                # Write operation info to lock file
                os.write(fd, f"{operation}:{os.getpid()}:{time.time()}\n".encode())
                break
            except BlockingIOError:
                # Lock held by another process, wait a bit
                time.sleep(0.1)
        
        yield acquired
        
    finally:
        if fd is not None:
            if acquired:
                # Release lock
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except Exception:
                    pass
            try:
                os.close(fd)
            except Exception:
                pass


def is_resolution_valid(resolution: str | None) -> bool:
    """Check if a resolution string is valid.
    
    Args:
        resolution: Resolution string like "1920x1080" or None
        
    Returns:
        True if resolution is valid and non-zero
    """
    if not resolution:
        return False
    if resolution == "0x0":
        return False
    
    # Parse and validate dimensions
    try:
        parts = resolution.split('x')
        if len(parts) != 2:
            return False
        width, height = int(parts[0]), int(parts[1])
        return width > 0 and height > 0
    except (ValueError, IndexError):
        return False


def reset_resolution_to_auto(rdp_output: str) -> bool:
    """Reset resolution using xrandr --auto.
    
    Args:
        rdp_output: RDP output name (e.g., "rdp0")
        
    Returns:
        True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            ['xrandr', '--output', rdp_output, '--auto'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def set_resolution_mode(rdp_output: str, resolution: str) -> bool:
    """Set a specific resolution mode using xrandr.
    
    Args:
        rdp_output: RDP output name (e.g., "rdp0")
        resolution: Resolution string like "1920x1080"
        
    Returns:
        True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            ['xrandr', '--output', rdp_output, '--mode', resolution],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def get_fallback_resolutions() -> list[str]:
    """Get list of common fallback resolutions to try.
    
    Returns:
        List of resolution strings in order of preference
    """
    return [
        '1920x1080',
        '1680x1050', 
        '1600x900',
        '1280x1024',
        '1024x768'
    ]
