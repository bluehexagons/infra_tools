"""Shared utilities for scheduled tasks (sync, scrub, etc)."""

from __future__ import annotations
import os
import shlex
from typing import Optional
from lib.config import SetupConfig
from lib.remote_utils import run
from lib.mount_utils import is_path_under_mnt, get_mount_ancestor


VALID_FREQUENCIES = ['hourly', 'daily', 'weekly', 'monthly']


def validate_frequency(frequency: str, label: str = "frequency") -> None:
    """Validate frequency parameter.
    
    Args:
        frequency: Frequency to validate
        label: Label for error messages
        
    Raises:
        ValueError: If frequency is invalid
    """
    if frequency not in VALID_FREQUENCIES:
        raise ValueError(
            f"Invalid {label} '{frequency}'. "
            f"Must be one of: {', '.join(VALID_FREQUENCIES)}"
        )


def get_timer_calendar(frequency: str, hour_offset: Optional[int] = None) -> str:
    """Get systemd timer OnCalendar value for frequency.
    
    Args:
        frequency: 'hourly', 'daily', 'weekly', or 'monthly'
        hour_offset: Hour to run (0-23), default None uses 2 AM for non-hourly
        
    Returns:
        OnCalendar string for systemd timer
    """
    if frequency == 'hourly':
        return '*-*-* *:00:00'
    
    hour = hour_offset if hour_offset is not None else 2
    
    calendars = {
        'daily': f'*-*-* {hour:02d}:00:00',
        'weekly': f'Mon *-*-* {hour:02d}:00:00',
        'monthly': f'*-*-01 {hour:02d}:00:00'
    }
    return calendars.get(frequency, f'*-*-* {hour:02d}:00:00')


def escape_systemd_description(value: str) -> str:
    """Escape value for safe use in systemd Description field."""
    return value.replace("\\", "\\\\").replace("\n", " ").replace('"', "'")


def check_path_on_smb_mount(path: str, config: SetupConfig) -> bool:
    """Check if path is on an SMB mount."""
    if not config.smb_mounts:
        return False
    for mount_spec in config.smb_mounts:
        mountpoint = mount_spec[0]
        if path.startswith(mountpoint + '/') or path == mountpoint:
            return True
    return False


def ensure_directory(path: str, username: str) -> None:
    """Ensure a directory exists, warn if under /mnt with no mount point.
    
    If the directory already exists, no ownership change is performed.
    Ownership is only set when the directory is first created.
    
    Args:
        path: Directory path to ensure exists
        username: Owner username for the directory
    """
    if os.path.exists(path):
        if not os.path.isdir(path):
            raise NotADirectoryError(f"Path exists but is not a directory: {path}")
        return
    if is_path_under_mnt(path):
        mount_ancestor = get_mount_ancestor(path)
        if not mount_ancestor:
            print(f"  ⚠ Warning: {path} is under /mnt but no mount point found")
            return
    os.makedirs(path, exist_ok=True)
    run(f"chown {shlex.quote(username)}:{shlex.quote(username)} {shlex.quote(path)}")
