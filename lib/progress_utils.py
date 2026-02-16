"""Progress tracking utilities for long-running operations.

Provides consistent progress logging for operations like sync and scrub
that can run for extended periods.
"""

from __future__ import annotations

import time
from typing import Any, Optional, Callable
from datetime import datetime


class ProgressTracker:
    """Tracks and logs progress for long-running operations.
    
    Automatically logs progress at specified intervals without spamming logs.
    """
    
    def __init__(
        self,
        interval_seconds: int = 30,
        logger: Optional[Any] = None,
        log_func: Optional[Callable[[str], None]] = None
    ):
        """Initialize progress tracker.
        
        Args:
            interval_seconds: Minimum seconds between progress logs (default: 30)
            logger: Optional logger instance with .info() method
            log_func: Optional custom logging function (overrides logger)
        """
        self.interval_seconds = interval_seconds
        self.logger = logger
        self.log_func = log_func
        self.start_time = time.time()
        self.last_log_time = time.time()
        
    def should_log(self) -> bool:
        """Check if enough time has passed to log progress."""
        current_time = time.time()
        return (current_time - self.last_log_time) >= self.interval_seconds
    
    def get_elapsed_seconds(self) -> float:
        """Get elapsed time since tracker was created."""
        return time.time() - self.start_time
    
    def log_if_due(self, message: str) -> bool:
        """Log progress message if interval has passed.
        
        Args:
            message: Progress message to log
            
        Returns:
            True if message was logged, False if skipped
        """
        if not self.should_log():
            return False
        
        self._log(message)
        self.last_log_time = time.time()
        return True
    
    def force_log(self, message: str) -> None:
        """Log progress message immediately, bypassing interval check."""
        self._log(message)
        self.last_log_time = time.time()
    
    def _log(self, message: str) -> None:
        """Internal logging method."""
        if self.log_func:
            self.log_func(message)
        elif self.logger:
            self.logger.info(message)
        else:
            print(message, flush=True)


def format_bytes(num_bytes: int) -> str:
    """Format bytes as human-readable string.
    
    Args:
        num_bytes: Number of bytes
        
    Returns:
        Formatted string (e.g., "1.23 GB", "456.78 MB", "789 KB")
    """
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / (1024 ** 3):.2f} GB"
    elif num_bytes >= 1024 ** 2:
        return f"{num_bytes / (1024 ** 2):.2f} MB"
    elif num_bytes >= 1024:
        return f"{num_bytes / 1024:.2f} KB"
    else:
        return f"{num_bytes} B"


def format_duration(seconds: float) -> str:
    """Format duration in seconds as human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string (e.g., "2h 34m", "45m 12s", "23s")
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"


def format_file_count(current: int, total: Optional[int] = None) -> str:
    """Format file count with optional total.
    
    Args:
        current: Current number of files
        total: Optional total number of files
        
    Returns:
        Formatted string (e.g., "1234/5678" or "1234")
    """
    if total and total > 0:
        return f"{current}/{total}"
    return str(current)


class ProgressMessage:
    """Builder for consistent progress messages."""
    
    def __init__(self, operation: str = "Progress"):
        """Initialize progress message builder.
        
        Args:
            operation: Operation name (e.g., "Progress", "Syncing", "Scrubbing")
        """
        self.parts = [operation + ":"]
    
    def add_percentage(self, percent: int) -> ProgressMessage:
        """Add percentage complete."""
        self.parts.append(f"{percent}% complete")
        return self
    
    def add_files(self, current: int, total: Optional[int] = None, label: str = "files") -> ProgressMessage:
        """Add file count."""
        self.parts.append(f"{format_file_count(current, total)} {label}")
        return self
    
    def add_bytes(self, num_bytes: int, label: str = "transferred") -> ProgressMessage:
        """Add byte count."""
        self.parts.append(f"{format_bytes(num_bytes)} {label}")
        return self
    
    def add_duration(self, seconds: float, label: str = "elapsed") -> ProgressMessage:
        """Add duration."""
        self.parts.append(f"{format_duration(seconds)} {label}")
        return self
    
    def add_custom(self, text: str) -> ProgressMessage:
        """Add custom text."""
        self.parts.append(text)
        return self
    
    def build(self) -> str:
        """Build the final message string."""
        return ", ".join(self.parts)


# Convenience function for one-off progress logging
def log_progress_if_due(
    last_log_time: float,
    message: str,
    logger: Optional[Any] = None,
    log_func: Optional[Callable[[str], None]] = None,
    interval_seconds: int = 30
) -> tuple[bool, float]:
    """Log progress if interval has passed since last log.
    
    This is a simpler alternative to ProgressTracker for cases where
    you want to manage the last_log_time yourself.
    
    Args:
        last_log_time: Unix timestamp of last progress log
        message: Progress message to log
        logger: Optional logger instance
        log_func: Optional custom logging function
        interval_seconds: Minimum seconds between logs
        
    Returns:
        Tuple of (was_logged: bool, new_last_log_time: float)
    """
    current_time = time.time()
    if (current_time - last_log_time) < interval_seconds:
        return (False, last_log_time)
    
    if log_func:
        log_func(message)
    elif logger:
        logger.info(message)
    else:
        print(message, flush=True)
    
    return (True, current_time)
