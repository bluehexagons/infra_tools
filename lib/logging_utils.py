"""Reusable logging helpers for infra tools services."""

from logging import Logger, Formatter, INFO, StreamHandler, getLogger
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5


def _ensure_fallback_handler(logger: Logger) -> None:
    if logger.handlers:
        return

    handler = StreamHandler(sys.stderr)
    handler.setFormatter(Formatter("%(message)s"))
    logger.addHandler(handler)


def get_rotating_logger(
    name: str,
    log_file: str,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_BACKUP_COUNT
) -> Logger:
    """Return a logger configured with a rotating file handler."""
    logger = getLogger(name)
    if not logger.handlers:
        logger.setLevel(INFO)
        logger.propagate = False

    log_path = Path(log_file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, IOError) as e:
        print(f"Error creating log directory {log_path.parent}: {e}", file=sys.stderr)
        _ensure_fallback_handler(logger)
        return logger

    log_file_path = str(log_path.resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == log_file_path:
            return logger

    try:
        handler = RotatingFileHandler(log_file_path, maxBytes=max_bytes, backupCount=backup_count)
    except (OSError, IOError) as e:
        print(f"Error opening log file {log_file_path}: {e}", file=sys.stderr)
        _ensure_fallback_handler(logger)
        return logger

    handler.setFormatter(Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def log_message(logger: Logger, message: str) -> None:
    """Write a log message with graceful error handling."""
    try:
        logger.info(message)
    except (OSError, IOError) as e:
        log_target = "unknown log"
        for handler in logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                log_target = handler.baseFilename
                break
        print(f"Error writing to log {log_target}: {e}", file=sys.stderr)
