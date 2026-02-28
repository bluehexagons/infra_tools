"""Centralized logging system for infra tools services.

This module provides a unified logging infrastructure for all infra_tools services
and systems. All errors and warnings are logged in a standardized format that can be
easily monitored by external monitoring systems.

Key Features:
- Rotating file handlers with configurable size and backup count
- Configurable log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Structured logging format with timestamps and severity levels
- Centralized log directory (/var/log/infra_tools/)
- Automatic fallback to stderr if file logging fails
- Service-specific loggers with consistent configuration
"""

from __future__ import annotations

from logging import (
    Logger, Formatter, StreamHandler, getLogger, INFO, WARNING
)
from logging.handlers import RotatingFileHandler, SysLogHandler
from pathlib import Path
from typing import Optional
import sys
import subprocess
from lib.types import BYTES_PER_MB

# Default log configuration
DEFAULT_LOG_MAX_BYTES = 5 * BYTES_PER_MB  # 5 MB
DEFAULT_LOG_BACKUP_COUNT = 5
DEFAULT_LOG_LEVEL = INFO
DEFAULT_LOG_DIR = "/var/log/infra_tools"

# Standard log format for all services
# Format: timestamp - severity - service - message
STANDARD_LOG_FORMAT = "%(asctime)s - %(levelname)-8s - %(name)s - %(message)s"
STANDARD_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ensure_fallback_handler(logger: Logger, level: int = INFO) -> None:
    """Add a stderr handler as fallback if no handlers are configured.
    
    Args:
        logger: Logger instance to add fallback handler to
        level: Log level for the handler
    """
    if logger.handlers:
        return

    handler = StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(Formatter(STANDARD_LOG_FORMAT, STANDARD_DATE_FORMAT))
    logger.addHandler(handler)


def get_standard_formatter() -> Formatter:
    """Get the standard formatter for all infra_tools logs.
    
    Returns:
        Configured Formatter instance
    """
    return Formatter(STANDARD_LOG_FORMAT, STANDARD_DATE_FORMAT)


def get_rotating_logger(
    name: str,
    log_file: str,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_BACKUP_COUNT,
    level: int = DEFAULT_LOG_LEVEL
) -> Logger:
    """Return a logger configured with a rotating file handler.
    
    Args:
        name: Logger name (typically service name)
        log_file: Path to log file
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup files to keep
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
    Returns:
        Configured Logger instance with rotating file handler
    """
    logger = getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)
        logger.propagate = False

    log_path = Path(log_file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError) as e:
        print(f"Error creating log directory {log_path.parent}: {e}", file=sys.stderr)
        _ensure_fallback_handler(logger, level)
        return logger

    log_file_path = str(log_path.resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == log_file_path:
            return logger

    try:
        handler = RotatingFileHandler(log_file_path, maxBytes=max_bytes, backupCount=backup_count)
        handler.setLevel(level)
        handler.setFormatter(get_standard_formatter())
        logger.addHandler(handler)
    except (OSError, IOError) as e:
        print(f"Error opening log file {log_file_path}: {e}", file=sys.stderr)
        _ensure_fallback_handler(logger, level)
        return logger

    return logger


def get_service_logger(
    service_name: str,
    log_subdir: Optional[str] = None,
    level: int = DEFAULT_LOG_LEVEL,
    use_syslog: bool = False,
    console_output: bool = True
) -> Logger:
    """Get a logger configured for a specific service.
    
    This is the recommended way to get a logger for infra_tools services.
    It automatically sets up the logger with:
    - Standard formatting
    - Rotating file handler
    - Optional syslog integration
    - Optional console output
    - Centralized log directory
    
    Args:
        service_name: Name of the service (e.g., 'scrub_par2', 'auto_update_node')
        log_subdir: Optional subdirectory under DEFAULT_LOG_DIR (e.g., 'scrub', 'web')
        level: Logging level
        use_syslog: Whether to also send logs to syslog
        console_output: Whether to also print to console (default: True)
        
    Returns:
        Configured Logger instance
        
    Example:
        logger = get_service_logger('auto_update_node', 'web')
        logger.info('Starting Node.js update')
        logger.warning('npm update failed, retrying')
        logger.error('Update failed after retries')
    """
    log_dir = Path(DEFAULT_LOG_DIR)
    if log_subdir:
        log_dir = log_dir / log_subdir
    log_file = log_dir / f"{service_name}.log"
    
    logger = get_rotating_logger(service_name, str(log_file), level=level)
    
    if console_output:
        # Check if stdout console handler already exists (explicit loop helps type-checkers)
        has_console = False
        for h in logger.handlers:
            if isinstance(h, StreamHandler):
                try:
                    # Accessing `.stream` is runtime-safe but the type checker
                    # may not know about this attribute on all handlers.
                    if h.stream is sys.stdout:  # type: ignore[attr-defined]
                        has_console = True
                        break
                except AttributeError:
                    # If handler doesn't expose `stream`, skip it
                    continue
        if not has_console:
            console_handler = StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            # Use simpler format for console: just the message with level prefix
            console_formatter = Formatter('%(message)s')
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)
    
    if use_syslog:
        try:
            syslog_handler = SysLogHandler(address='/dev/log')
            syslog_handler.setLevel(level)
            syslog_handler.setFormatter(Formatter(f'{service_name}: %(message)s'))
            logger.addHandler(syslog_handler)
        except (OSError, IOError):
            # Syslog not available, continue without it
            pass
    
    return logger


def log_message(logger: Logger, message: str, level: int = INFO) -> None:
    """Write a log message with graceful error handling.
    
    Args:
        logger: Logger instance to use
        message: Message to log
        level: Log level (INFO, WARNING, ERROR, etc.)
    """
    try:
        logger.log(level, message)
    except (OSError, IOError) as e:
        log_target = "unknown log"
        for handler in logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                log_target = handler.baseFilename
                break
        print(f"Error writing to log {log_target}: {e}", file=sys.stderr)


def ensure_log_directory(subdir: Optional[str] = None) -> Path:
    """Ensure the log directory exists and return its path.
    
    Args:
        subdir: Optional subdirectory under DEFAULT_LOG_DIR
        
    Returns:
        Path to the log directory
    """
    log_dir = Path(DEFAULT_LOG_DIR)
    if subdir:
        log_dir = log_dir / subdir
    
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError) as e:
        print(f"Error creating log directory {log_dir}: {e}", file=sys.stderr)
    
    return log_dir


def log_subprocess_result(
    logger: Logger,
    action: str,
    result: subprocess.CompletedProcess[str],
    success_level: int = INFO,
    failure_level: int = WARNING
) -> bool:
    """Log concise command result details and return success state."""
    if result.returncode == 0:
        logger.log(success_level, f"✓ {action}")
        return True

    stderr_raw = result.stderr or ""
    if isinstance(stderr_raw, bytes):
        stderr_raw = stderr_raw.decode(errors="replace")
    stderr = stderr_raw.strip().splitlines()
    if stderr:
        detail_lines = stderr[:3]
        details = " | ".join(detail_lines)
        if len(stderr) > 3:
            details += " | ..."
    else:
        details = f"exit code {result.returncode}"
    logger.log(failure_level, f"⚠ {action} failed: {details}")
    return False
