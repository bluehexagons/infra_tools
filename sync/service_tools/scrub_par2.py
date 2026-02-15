#!/usr/bin/env python3
"""Par2 scrub operations for data integrity checking.

This script creates par2 parity files, verifies files, and repairs corrupted files.
Enhanced with transaction support and improved error recovery.
Supports sending notifications on completion or failure.
"""

from __future__ import annotations

import sys
import os
import subprocess
import time
from glob import glob, escape
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_rotating_logger, log_message
from lib.operation_log import create_operation_logger
from lib.transaction import create_transaction
from lib.validation import validate_filesystem_path
from lib.disk_utils import estimate_operation_duration

PAR2_EXTENSION = ".par2"
PAR2_VOLUME_MARKER = f"{PAR2_EXTENSION}.vol"
PAR2_MTIME_TOLERANCE_SECONDS = 1.0
PAR2_CREATE_RETRIES = 3
PAR2_CREATE_BACKOFF_SECONDS = 2
PAR2_CREATE_MAX_BACKOFF_SECONDS = 30

_LOGGERS: dict[str, Any] = {}


def log(message: str, log_file: str) -> None:
    """Append message to log file."""
    logger = _LOGGERS.get(log_file)
    if logger is None:
        logger = get_rotating_logger(f"scrub_par2:{log_file}", log_file)
        _LOGGERS[log_file] = logger
    log_message(logger, message)


def _remove_par2_files(par2_base: str, log_file: str) -> None:
    """Remove par2 files for a base path."""
    for par2_file in glob(f"{escape(par2_base)}*"):
        try:
            os.remove(par2_file)
        except (IOError, OSError) as e:
            log(f"Error removing par2 file {par2_file}: {e}", log_file)


def create_par2(
    file_path: str,
    directory: str,
    database: str,
    redundancy: int,
    log_file: str,
    force: bool = False,
    operation_logger: Optional[Any] = None,
    transaction: Optional[Any] = None
) -> bool:
    """Create par2 parity file if it doesn't exist.
    
    Args:
        file_path: Path to file to protect
        directory: Base directory being protected
        database: Database directory for par2 files
        redundancy: Redundancy percentage
        log_file: Log file path
        force: Whether to recreate existing par2 files
        operation_logger: Optional operation logger for enhanced logging
        transaction: Optional transaction for atomic operations
        
    Returns:
        True if created or already exists, False on error
    """
    relative_path = os.path.relpath(file_path, directory)
    par2_base = os.path.join(database, f"{relative_path}{PAR2_EXTENSION}")
    
    # Enhanced validation
    try:
        validate_filesystem_path(file_path, must_exist=True)
        validate_filesystem_path(database, check_writable=True)
    except ValueError as e:
        log(f"Validation error for {relative_path}: {e}", log_file)
        if operation_logger:
            operation_logger.log_error("validation_failed", str(e), {"file": relative_path})
        return False
    
    par2_files = glob(f"{escape(par2_base)}*")
    
    if par2_files:
        if not force:
            # Check if par2 file is newer than source file
            try:
                if os.path.exists(par2_base):
                    file_mtime = os.path.getmtime(file_path)
                    par2_mtime = os.path.getmtime(par2_base)
                    
                    if file_mtime <= par2_mtime + PAR2_MTIME_TOLERANCE_SECONDS:
                        log(f"Par2 already up-to-date for: {relative_path}", log_file)
                        if operation_logger:
                            operation_logger.log_step("par2_check", "completed", f"Par2 up-to-date: {relative_path}")
                        return True
            except OSError as e:
                log(f"Cannot check file times for {relative_path}: {e}, forcing recreation", log_file)
                force = True
        
        # Atomic removal of existing par2 files
        def remove_existing_par2():
            _remove_par2_files(par2_base, log_file)
        
        def restore_par2_backup():
            # In a real implementation, this would restore from backup
            log(f"Warning: Cannot restore par2 files for {relative_path} (no backup available)", log_file)
        
        if transaction:
            transaction.add_step(
                remove_existing_par2,
                restore_par2_backup,
                f"Remove existing par2 files for {relative_path}",
                f"remove_par2_{relative_path.replace('/', '_')}"
            )
        else:
            remove_existing_par2()
    
    log(f"Creating par2 for: {relative_path} (redundancy: {redundancy}%)", log_file)
    
    # Estimate operation duration
    try:
        file_size = os.path.getsize(file_path)
        estimated_duration = estimate_operation_duration('par2', file_size // (1024 * 1024))
        if operation_logger:
            operation_logger.log_metric("estimated_duration_seconds", estimated_duration, "seconds")
    except OSError:
        estimated_duration = 60  # Default 1 minute
    
    os.makedirs(os.path.dirname(par2_base), exist_ok=True)
    
    def create_par2_atomic():
        for attempt in range(PAR2_CREATE_RETRIES):
            try:
                start_time = time.time()
                subprocess.run(
                    ['par2', 'create', '-B', directory, f'-r{redundancy}', '-n1', par2_base, relative_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=True,
                    text=True,
                    cwd=directory
                )
                
                creation_time = time.time() - start_time
                if operation_logger:
                    operation_logger.log_metric("par2_creation_time_seconds", creation_time, "seconds")
                    operation_logger.log_metric("par2_file_size_mb", os.path.getsize(file_path) // (1024 * 1024), "MB")
                
                log(f"✓ Created par2 for {relative_path} in {creation_time:.1f}s", log_file)
                return True
                
            except subprocess.CalledProcessError as e:
                error_msg = f"Error creating par2 for {relative_path} (attempt {attempt + 1}): {e.stdout}"
                log(error_msg, log_file)
                if operation_logger:
                    operation_logger.log_error("par2_creation_failed", error_msg, 
                                          {"file": relative_path, "attempt": attempt + 1})
                
                _remove_par2_files(par2_base, log_file)
                if attempt < PAR2_CREATE_RETRIES - 1:
                    delay = min(PAR2_CREATE_BACKOFF_SECONDS * (2 ** attempt), PAR2_CREATE_MAX_BACKOFF_SECONDS)
                    log(f"Retrying par2 create for {relative_path} in {delay}s", log_file)
                    time.sleep(delay)
        
        return False
    
    def cleanup_partial_par2():
        _remove_par2_files(par2_base, log_file)
        log(f"Cleaned up partial par2 files for {relative_path}", log_file)
    
    if transaction:
        transaction.add_step(
            create_par2_atomic,
            cleanup_partial_par2,
            f"Create par2 files for {relative_path}",
            f"create_par2_{relative_path.replace('/', '_')}"
        )
        return transaction.execute()  # Execute just this step
    else:
        return create_par2_atomic()


def _par2_base_from_parity_file(parity_path: str) -> str:
    """Get par2 base path from any parity file."""
    if PAR2_VOLUME_MARKER in parity_path:
        return parity_path.split(PAR2_VOLUME_MARKER, 1)[0] + PAR2_EXTENSION
    return parity_path


def _cleanup_orphan_par2(
    directory: str,
    database: str,
    existing_files: set[str],
    log_file: str,
    operation_logger: Optional[Any] = None,
    transaction: Optional[Any] = None
) -> None:
    """Remove parity files for data files that no longer exist."""
    checked_bases: set[str] = set()
    orphan_count = 0
    total_orphan_size = 0
    
    for root, _, files in os.walk(database):
        for filename in files:
            if not filename.endswith(PAR2_EXTENSION):
                continue
            par2_path = os.path.join(root, filename)
            par2_base = _par2_base_from_parity_file(par2_path)
            if par2_base in checked_bases:
                continue
            checked_bases.add(par2_base)
            relative_par2 = os.path.relpath(par2_base, database)
            if relative_par2.endswith(PAR2_EXTENSION):
                relative_data = relative_par2[:-len(PAR2_EXTENSION)]
            else:
                relative_data = relative_par2
            if relative_data in existing_files:
                continue
            
            # Enhanced orphan validation
            try:
                # Calculate orphan size before removal
                orphan_par2_files = glob(f"{escape(par2_base)}*")
                orphan_size = sum(os.path.getsize(f) for f in orphan_par2_files if os.path.exists(f))
                total_orphan_size += orphan_size
                
                log(f"Removing orphan par2 for deleted file: {relative_data} ({orphan_size // 1024}KB)", log_file)
                if operation_logger:
                    operation_logger.log_metric("orphan_file_removed", relative_data, "filename")
                    operation_logger.log_metric("orphan_size_kb", orphan_size // 1024, "KB")
                
                def remove_orphan():
                    _remove_par2_files(par2_base, log_file)
                
                # No rollback needed for orphan removal
                if transaction:
                    transaction.add_step(
                        remove_orphan,
                        lambda: None,  # No-op rollback
                        f"Remove orphan par2 for {relative_data}",
                        f"remove_orphan_{relative_data.replace('/', '_')}"
                    )
                else:
                    remove_orphan()
                
                orphan_count += 1
                
            except OSError as e:
                log(f"Error removing orphan par2 for {relative_data}: {e}", log_file)
                if operation_logger:
                    operation_logger.log_error("orphan_removal_failed", str(e), 
                                          {"file": relative_data})
    
    if orphan_count > 0:
        log(f"Cleaned up {orphan_count} orphan par2 sets, freed {total_orphan_size // 1024 // 1024}MB", log_file)
        if operation_logger:
            operation_logger.log_metric("total_orphan_files_removed", orphan_count, "count")
            operation_logger.log_metric("total_orphan_size_mb", total_orphan_size // 1024 // 1024, "MB")


def verify_repair(file_path: str, directory: str, database: str, log_file: str) -> bool:
    """Verify file integrity and repair if needed.
    
    Args:
        file_path: Path to file to verify
        directory: Base directory being protected
        database: Database directory for par2 files
        log_file: Log file path
        
    Returns:
        True if a repair was performed, False otherwise
    """
    relative_path = os.path.relpath(file_path, directory)
    par2_base = os.path.join(database, f"{relative_path}{PAR2_EXTENSION}")
    
    if not os.path.exists(par2_base):
        return False
    
    log(f"Verifying: {relative_path}", log_file)
    
    try:
        subprocess.run(
            ['par2', 'verify', '-B', directory, par2_base],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            text=True,
            cwd=directory
        )
        return False
    except subprocess.CalledProcessError:
        log(f"Verification failed for: {relative_path}", log_file)
        log("Attempting repair...", log_file)
        
        try:
            subprocess.run(
                ['par2', 'repair', '-B', directory, par2_base],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
                text=True,
                cwd=directory
            )
            log(f"✓ Repaired: {relative_path}", log_file)
            return True
        except subprocess.CalledProcessError as e:
            log(f"✗ Repair failed: {relative_path}", log_file)
            log(f"  Error: {e.stdout}", log_file)
            return False


def scrub_directory(directory: str, database: str, redundancy: int, log_file: str, verify: bool = True) -> None:
    """Scrub directory: create par2 files and optionally verify/repair.
    
    Args:
        directory: Directory to scrub
        database: Database directory for par2 files
        redundancy: Redundancy percentage
        log_file: Log file path
        verify: Whether to verify and repair (False for fast initial creation)
    """
    # Load notification configs from machine state
    notification_configs = []
    try:
        from lib.machine_state import load_setup_config
        from lib.notifications import parse_notification_args
        setup_config = load_setup_config()
        if setup_config and 'notify_specs' in setup_config:
            notification_configs = parse_notification_args(setup_config['notify_specs'])
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        # If notification loading fails, just log and continue without notifications
        log(f"Warning: Failed to load notification configs: {e}", log_file)
    
    # Enhanced logging with operation logger
    operation_logger = create_operation_logger(
        "scrub_par2", 
        directory=directory, 
        database=database, 
        redundancy=redundancy, 
        verify=verify
    )
    transaction = create_transaction(f"scrub_{int(time.time())}", operation_logger, timeout_seconds=7200)  # 2 hours
    
    try:
        log("=" * 60, log_file)
        log(f"Scrub started: {datetime.now()}", log_file)
        log(f"Directory: {directory}", log_file)
        log(f"Database: {database}", log_file)
        log(f"Redundancy: {redundancy}%", log_file)
        log(f"Verify: {verify}", log_file)
        log("=" * 60, log_file)
        
        operation_logger.log_step("scrub_initiated", "started", 
                               f"Starting scrub of {directory} with {redundancy}% redundancy")
        
        # Enhanced validation
        transaction.add_validation_step(
            lambda: validate_filesystem_path(directory, must_exist=True),
            f"Validate directory exists: {directory}",
            "validate_directory"
        )
        transaction.add_validation_step(
            lambda: validate_filesystem_path(database, check_writable=True),
            f"Validate database directory writable: {database}",
            "validate_database"
        )
        
        if not transaction.execute():
            operation_logger.log_error("validation_failed", "Directory validation failed")
            log("Validation failed, aborting scrub", log_file)
            
            # Send validation failure notification
            if notification_configs:
                try:
                    from lib.notifications import send_notification
                    # Reuse existing logger from _LOGGERS cache
                    notif_logger = _LOGGERS.get(log_file)
                    send_notification(
                        notification_configs,
                        subject="Error: Scrub validation failed",
                        job="scrub",
                        status="error",
                        message=f"Validation failed for {directory}",
                        details=None,
                        logger=notif_logger
                    )
                except Exception as notify_err:
                    log(f"Warning: Failed to send notification: {notify_err}", log_file)
            
            return
        
        os.makedirs(database, exist_ok=True)
        
        database_path = Path(database).resolve()
        existing_files: set[str] = set()
        files_processed = 0
        files_updated = 0
        files_verified = 0
        files_repaired = 0
        total_file_size = 0
        
        # Create checkpoint after validation
        transaction.create_checkpoint("validation_complete")
        
        for root, dirs, files in os.walk(directory):
            root_path = Path(root).resolve()
            
            if root_path == database_path or database_path in root_path.parents:
                dirs[:] = []
                continue
            
            dirs[:] = [d for d in dirs 
                       if not _is_under_database(root_path / d, database_path)]
            
            for filename in files:
                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, directory)
                existing_files.add(relative_path)
                par2_base = os.path.join(database, f"{relative_path}{PAR2_EXTENSION}")
                force = False
                
                try:
                    file_size = os.path.getsize(file_path)
                    total_file_size += file_size
                except OSError:
                    continue
                
                if os.path.exists(par2_base):
                    try:
                        if os.path.getmtime(file_path) > os.path.getmtime(par2_base) + PAR2_MTIME_TOLERANCE_SECONDS:
                            log(f"Updating par2 for modified file: {relative_path}", log_file)
                            force = True
                            files_updated += 1
                    except (IOError, OSError) as e:
                        log(f"Error checking par2 timestamps for {relative_path}: {e}", log_file)
                        force = True
                
                # Create par2 with transaction support
                success = create_par2(file_path, directory, database, redundancy, log_file, 
                                    force=force, operation_logger=operation_logger, transaction=transaction)
                if success:
                    files_processed += 1
                
                if verify:
                    was_repaired = verify_repair(file_path, directory, database, log_file)
                    files_verified += 1
                    if was_repaired:
                        files_repaired += 1
        
        # Create checkpoint before cleanup
        transaction.create_checkpoint("par2_creation_complete")
        
        # Enhanced orphan cleanup
        _cleanup_orphan_par2(directory, database, existing_files, log_file, 
                           operation_logger=operation_logger, transaction=transaction)
        
        # Final metrics
        operation_logger.log_metric("files_processed", files_processed, "count")
        operation_logger.log_metric("files_updated", files_updated, "count")
        operation_logger.log_metric("files_verified", files_verified, "count")
        operation_logger.log_metric("files_repaired", files_repaired, "count")
        operation_logger.log_metric("total_file_size_mb", total_file_size // (1024 * 1024), "MB")
        
        # Execute any remaining transaction steps
        if not transaction.execute():
            operation_logger.log_error("finalization_failed", "Scrub finalization failed")
        else:
            operation_logger.log_step("scrub_completed", "completed", 
                                   f"Successfully processed {files_processed} files")
        
        log(f"Scrub completed: {datetime.now()}", log_file)
        log(f"Files processed: {files_processed}, Updated: {files_updated}, Verified: {files_verified}, Repaired: {files_repaired}", log_file)
        log("", log_file)
        
        operation_logger.complete("completed", 
                              f"Scrub completed: {files_processed} files processed, {files_repaired} repaired")
        
        # Send success notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                status = "warning" if files_repaired > 0 else "good"
                message = f"Processed {files_processed} files"
                if files_updated > 0:
                    message += f", updated {files_updated}"
                if files_repaired > 0:
                    message += f", repaired {files_repaired}"
                if files_verified > 0:
                    message += f", verified {files_verified}"
                
                details = f"""Scrub Summary:
Directory: {directory}
Files processed: {files_processed}
Files updated: {files_updated}
Files verified: {files_verified}
Files repaired: {files_repaired}
Total size: {total_file_size // (1024 * 1024)} MB
Redundancy: {redundancy}%
"""
                
                # Reuse existing logger from _LOGGERS cache
                notif_logger = _LOGGERS.get(log_file)
                send_notification(
                    notification_configs,
                    subject=f"{'Warning' if files_repaired > 0 else 'Success'}: Scrub completed",
                    job="scrub",
                    status=status,
                    message=message,
                    details=details,
                    logger=notif_logger
                )
            except Exception as notify_err:
                log(f"Warning: Failed to send notification: {notify_err}", log_file)
        
    except Exception as e:
        operation_logger.log_error("scrub_failed", str(e))
        log(f"Scrub failed: {e}", log_file)
        
        # Send error notification
        if notification_configs:
            try:
                from lib.notifications import send_notification
                # Reuse existing logger from _LOGGERS cache
                notif_logger = _LOGGERS.get(log_file)
                send_notification(
                    notification_configs,
                    subject="Error: Scrub failed",
                    job="scrub",
                    status="error",
                    message=f"Scrub failed for {directory}: {str(e)}",
                    details=None,
                    logger=notif_logger
                )
            except Exception as notify_err:
                log(f"Warning: Failed to send error notification: {notify_err}", log_file)
        
        if transaction:
            transaction.rollback(str(e))
        raise


def _is_under_database(path: Path, database_path: Path) -> bool:
    """Check if path is under database directory."""
    path_resolved = path.resolve()
    return path_resolved == database_path or database_path in path_resolved.parents


def main():
    """Main entry point."""
    if len(sys.argv) < 5:
        print("Usage: scrub_par2.py <directory> <database> <redundancy> <log_file> [--no-verify]")
        return 1
    
    directory = sys.argv[1]
    database = sys.argv[2]
    redundancy = int(sys.argv[3])
    log_file = sys.argv[4]
    verify = '--no-verify' not in sys.argv
    
    try:
        scrub_directory(directory, database, redundancy, log_file, verify)
        return 0
    except Exception as e:
        log(f"Error: {e}", log_file)
        return 1


if __name__ == '__main__':
    sys.exit(main())
