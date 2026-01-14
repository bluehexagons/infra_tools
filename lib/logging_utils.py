"""Reusable logging helpers for infra tools services."""

from logging import Logger, Formatter, getLogger
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5


def get_rotating_logger(
    name: str,
    log_file: str,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_BACKUP_COUNT
) -> Logger:
    """Return a logger configured with a rotating file handler."""
    logger = getLogger(name)
    logger.setLevel("INFO")
    logger.propagate = False

    log_path = Path(log_file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError) as e:
        print(f"Error creating log directory {log_path.parent}: {e}", file=sys.stderr)

    log_file_path = str(log_path.resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == log_file_path:
            return logger

    try:
        handler = RotatingFileHandler(log_file_path, maxBytes=max_bytes, backupCount=backup_count)
    except (OSError, IOError) as e:
        print(f"Error opening log file {log_file_path}: {e}", file=sys.stderr)
        return logger

    handler.setFormatter(Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def log_message(logger: Logger, message: str, log_file: str) -> None:
    """Write a log message with graceful error handling."""
    try:
        logger.info(message)
    except (OSError, IOError, ValueError) as e:
        print(f"Error writing to log {log_file}: {e}", file=sys.stderr)
