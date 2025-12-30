"""Shared utilities for scheduled tasks (sync, scrub, etc)."""

from typing import List
from lib.config import SetupConfig


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


def get_timer_calendar(frequency: str, hour_offset: int = None) -> str:
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
