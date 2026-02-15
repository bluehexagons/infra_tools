#!/usr/bin/env python3
"""Unified storage operations orchestrator for sync and scrub.

This script is the single entry point for all storage operations.
It reads sync/scrub specs from machine state and executes them in order:
1. Sync operations (rsync source -> destination)
2. Scrub full verify+repair (if interval elapsed)
3. Parity updates (fast mode for new/changed files)

Uses file locking to prevent concurrent runs.
"""

from __future__ import annotations

import sys
import os
import io
import json
import fcntl
import time
from datetime import datetime
from typing import Optional

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger
from lib.notifications import send_notification, parse_notification_args
from lib.machine_state import load_setup_config
from lib.mount_utils import get_mount_ancestor
from lib.task_utils import needs_mount_check
from lib.runtime_config import RuntimeConfig

# Constants
LOCK_FILE = "/run/lock/storage-ops.lock"
STATE_FILE = "/var/lib/storage-ops/last_run.json"
LOG_DIR = "/var/log/storage-ops"

# Frequency in seconds
FREQUENCY_SECONDS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "biweekly": 1209600,  # 14 days
    "monthly": 2592000,
    "bimonthly": 5184000,  # ~60 days
}


class OperationLock:
    """Context manager for storage operations lock."""
    
    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self.lock_file: Optional[io.TextIOWrapper] = None
        self.acquired = False
    
    def acquire(self, blocking: bool = False, timeout: float = 300.0) -> bool:
        """Acquire lock with optional blocking and timeout."""
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        
        # Open without truncation so a failed lock attempt doesn't modify the file.
        self.lock_file = open(self.lock_path, 'a+')
        try:
            if blocking:
                start_time = time.time()
                while True:
                    try:
                        fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self.acquired = True
                        return True
                    except (IOError, OSError):
                        if time.time() - start_time >= timeout:
                            if self.lock_file:
                                self.lock_file.close()
                                self.lock_file = None
                            return False
                        time.sleep(1.0)
            else:
                try:
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.acquired = True
                    return True
                except (IOError, OSError):
                    if self.lock_file:
                        self.lock_file.close()
                        self.lock_file = None
                    return False
        except Exception:
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            raise
    
    def release(self) -> None:
        """Release lock and cleanup."""
        if self.acquired and self.lock_file:
            try:
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self.lock_file.close()
                os.unlink(self.lock_path)
            except (IOError, OSError):
                pass
            finally:
                self.acquired = False
                self.lock_file = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def load_last_run() -> dict:
    """Load last run timestamps from state file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_last_run(state: dict) -> None:
    """Save last run timestamps to state file."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def is_operation_due(last_run: dict, op_id: str, interval: str) -> bool:
    """Check if an operation is due based on its interval."""
    last_time = last_run.get(op_id)
    if last_time is None:
        return True
    
    interval_sec = FREQUENCY_SECONDS.get(interval, FREQUENCY_SECONDS["hourly"])
    return (time.time() - last_time) >= interval_sec


def resolve_scrub_database_path(directory: str, database: str) -> str:
    """Resolve scrub database path, handling relative paths.
    
    Scrub specs may store the database as a relative path (e.g. '.pardatabase').
    This must be resolved relative to the scrub directory before use.
    """
    if not database.startswith('/'):
        database = os.path.join(directory, database)
    return os.path.normpath(database)


def get_sync_op_id(source: str, destination: str) -> str:
    """Generate unique ID for sync operation."""
    return f"sync:{source}:{destination}"


def get_scrub_op_id(directory: str, database: str) -> str:
    """Generate unique ID for scrub operation."""
    return f"scrub:{directory}:{database}"


def validate_mounts_for_operation(paths: list[str], config: RuntimeConfig, operation_type: str) -> tuple[bool, str]:
    """Validate that all required mounts are available."""
    for path in paths:
        if needs_mount_check(path, config):
            if not os.path.exists(path):
                return False, f"Path {path} not available (possibly unmounted)"
            mount_ancestor = get_mount_ancestor(path)
            if not mount_ancestor:
                return False, f"No mounted filesystem found for {path} ({operation_type})"
            if not os.path.ismount(mount_ancestor):
                return False, f"Mount {mount_ancestor} not available for {operation_type}"

    return True, ""


def run_sync(source: str, destination: str, logger) -> tuple[bool, str]:
    """Execute rsync sync operation."""
    from sync.service_tools.sync_rsync import run_rsync_with_notifications
    
    logger.info(f"Starting sync: {source} -> {destination}")
    
    try:
        result = run_rsync_with_notifications(source, destination)
        return result == 0, f"Sync completed with exit code {result}"
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return False, str(e)


def run_scrub(directory: str, database: str, redundancy: str, verify: bool, logger) -> tuple[bool, str]:
    """Execute scrub operation."""
    from sync.service_tools.scrub_par2 import scrub_directory
    
    mode = "full verify+repair" if verify else "parity update only"
    logger.info(f"Starting scrub ({mode}): {directory}")
    
    log_dir = LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    
    # Generate log file path for this scrub
    from hashlib import md5
    scrub_id = md5(f"{directory}:{database}".encode()).hexdigest()[:8]
    log_file = f"{log_dir}/scrub-{scrub_id}.log"
    
    try:
        redundancy_int = int(redundancy.rstrip('%'))
        scrub_directory(directory, database, redundancy_int, log_file, verify)
        return True, f"Scrub completed for {directory}"
    except ValueError as e:
        error_msg = f"Invalid redundancy value '{redundancy}': {e}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        logger.error(f"Scrub failed: {e}")
        return False, str(e)


def execute_storage_operations() -> dict:
    """Main orchestrator function."""
    logger = get_service_logger('storage-ops', 'operations', use_syslog=True, console_output=True)
    
    results = {
        "syncs": [],
        "scrubs": [],
        "parity_updates": [],
        "start_time": datetime.now().isoformat(),
        "end_time": None,
        "success": True,
    }
    
    # Load configuration
    config_dict = load_setup_config()
    if not config_dict:
        logger.error("No configuration found in machine state")
        results["success"] = False
        return results
    
    config = RuntimeConfig.from_dict(config_dict)
    notification_configs = parse_notification_args(config.notify_specs)
    
    logger.info(f"Loaded {len(config.sync_specs)} sync specs, {len(config.scrub_specs)} scrub specs")
    
    if not config.has_storage_ops():
        logger.info("No storage operations configured")
        results["end_time"] = datetime.now().isoformat()
        return results
    
    # Load last run state
    last_run = load_last_run()
    new_state = last_run.copy()
    
    # Execute syncs first (always run if due)
    for spec in config.sync_specs:
        if len(spec) != 3:
            logger.error(f"Invalid sync spec: {spec}")
            results["syncs"].append({"spec": spec, "success": False, "error": "Invalid spec"})
            continue
        
        source, destination, interval = spec
        op_id = get_sync_op_id(source, destination)
        
        if is_operation_due(last_run, op_id, interval):
            # Validate mounts
            valid, error_msg = validate_mounts_for_operation([source, destination], config, "sync")
            if not valid:
                logger.warning(f"Skipping sync {source} -> {destination}: {error_msg}")
                results["syncs"].append({
                    "source": source,
                    "destination": destination,
                    "success": False,
                    "error": error_msg,
                    "skipped": True
                })
                continue
            
            success, message = run_sync(source, destination, logger)
            results["syncs"].append({
                "source": source,
                "destination": destination,
                "success": success,
                "message": message
            })
            
            if success:
                new_state[op_id] = time.time()
            else:
                results["success"] = False
    
    # Execute full scrubs if due
    for spec in config.scrub_specs:
        if len(spec) != 4:
            logger.error(f"Invalid scrub spec: {spec}")
            results["scrubs"].append({"spec": spec, "success": False, "error": "Invalid spec"})
            continue
        
        directory, database, redundancy, interval = spec
        op_id = get_scrub_op_id(directory, database)
        resolved_database = resolve_scrub_database_path(directory, database)
        
        if is_operation_due(last_run, op_id, interval):
            # Validate mounts
            valid, error_msg = validate_mounts_for_operation([directory, resolved_database], config, "scrub")
            if not valid:
                logger.warning(f"Skipping scrub {directory}: {error_msg}")
                results["scrubs"].append({
                    "directory": directory,
                    "success": False,
                    "error": error_msg,
                    "skipped": True
                })
                continue
            
            success, message = run_scrub(directory, resolved_database, redundancy, verify=True, logger=logger)
            results["scrubs"].append({
                "directory": directory,
                "database": resolved_database,
                "success": success,
                "message": message,
                "full": True
            })
            
            if success:
                new_state[op_id] = time.time()
            else:
                results["success"] = False
    
    # Execute parity updates for all scrub specs (always run)
    # This ensures new files get parity protection quickly
    for spec in config.scrub_specs:
        if len(spec) != 4:
            continue
        
        directory, database, redundancy, interval = spec
        resolved_database = resolve_scrub_database_path(directory, database)
        
        # Validate mounts
        valid, error_msg = validate_mounts_for_operation([directory, resolved_database], config, "parity update")
        if not valid:
            logger.warning(f"Skipping parity update for {directory}: {error_msg}")
            results["parity_updates"].append({
                "directory": directory,
                "success": False,
                "error": error_msg,
                "skipped": True
            })
            continue
        
        success, message = run_scrub(directory, resolved_database, redundancy, verify=False, logger=logger)
        results["parity_updates"].append({
            "directory": directory,
            "database": resolved_database,
            "success": success,
            "message": message
        })
        
        if not success:
            results["success"] = False
    
    # Save updated state
    save_last_run(new_state)
    
    results["end_time"] = datetime.now().isoformat()
    
    # Send notification if configured
    if notification_configs:
        send_operation_notification(results, notification_configs, logger)
    
    return results


def send_operation_notification(results: dict, notification_configs: list, logger) -> None:
    """Send summary notification for operations."""
    success_count = sum(1 for s in results["syncs"] if s.get("success"))
    total_syncs = len(results["syncs"])
    
    scrub_success_count = sum(1 for s in results["scrubs"] if s.get("success"))
    total_scrubs = len(results["scrubs"])
    
    parity_success_count = sum(1 for s in results["parity_updates"] if s.get("success"))
    total_parity = len(results["parity_updates"])
    
    if results["success"]:
        status = "good"
        subject = "Storage operations completed"
    else:
        status = "error"
        subject = "Storage operations completed with errors"
    
    message = f"Syncs: {success_count}/{total_syncs}, Scrubs: {scrub_success_count}/{total_scrubs}, Parity updates: {parity_success_count}/{total_parity}"
    
    details = f"""Storage Operations Summary
==========================
Start: {results["start_time"]}
End: {results["end_time"]}

Sync Operations:
{format_operation_results(results["syncs"])}

Full Scrub Operations:
{format_operation_results(results["scrubs"])}

Parity Update Operations:
{format_operation_results(results["parity_updates"])}
"""
    
    try:
        send_notification(
            notification_configs,
            subject=subject,
            job="storage-ops",
            status=status,
            message=message,
            details=details,
            logger=logger
        )
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def format_operation_results(operations: list) -> str:
    """Format operation results for notification."""
    if not operations:
        return "  None"
    
    lines = []
    for op in operations:
        success_mark = "✓" if op.get("success") else "✗"
        if op.get("skipped"):
            success_mark = "○"
        
        if "source" in op:
            name = f"{op['source']} -> {op['destination']}"
        elif "directory" in op:
            name = op['directory']
        else:
            name = str(op.get("spec", "unknown"))
        
        lines.append(f"  {success_mark} {name}")
        if op.get("error"):
            lines.append(f"    Error: {op['error']}")
        elif op.get("message"):
            lines.append(f"    {op['message']}")
    
    return "\n".join(lines)


def main():
    """Main entry point."""
    logger = get_service_logger('storage-ops', 'lock', use_syslog=True, console_output=True)
    
    # Acquire lock (non-blocking) - if another instance is running, exit cleanly
    with OperationLock(LOCK_FILE) as lock:
        if not lock.acquire(blocking=False):
            logger.info("Another storage-ops instance is already running, skipping this run")
            return 0
        
        # Execute operations
        results = execute_storage_operations()
        
        # Return exit code based on success
        return 0 if results["success"] else 1


if __name__ == '__main__':
    sys.exit(main())
