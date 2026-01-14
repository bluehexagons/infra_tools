#!/usr/bin/env python3
"""Par2 scrub operations for data integrity checking.

This script creates par2 parity files, verifies files, and repairs corrupted files.
"""

import sys
import os
import subprocess
import time
from glob import glob, escape
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from lib.logging_utils import get_rotating_logger, log_message

PAR2_EXTENSION = ".par2"
PAR2_VOLUME_MARKER = f"{PAR2_EXTENSION}.vol"
PAR2_MTIME_TOLERANCE_SECONDS = 1.0
PAR2_CREATE_RETRIES = 3
PAR2_CREATE_BACKOFF_SECONDS = 2
PAR2_CREATE_MAX_BACKOFF_SECONDS = 30


def log(message: str, log_file: str) -> None:
    """Append message to log file."""
    logger = get_rotating_logger(f"scrub_par2:{log_file}", log_file)
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
    force: bool = False
) -> bool:
    """Create par2 parity file if it doesn't exist.
    
    Args:
        file_path: Path to file to protect
        directory: Base directory being protected
        database: Database directory for par2 files
        redundancy: Redundancy percentage
        log_file: Log file path
        force: Whether to recreate existing par2 files
        
    Returns:
        True if created or already exists, False on error
    """
    relative_path = os.path.relpath(file_path, directory)
    par2_base = os.path.join(database, f"{relative_path}{PAR2_EXTENSION}")
    
    par2_files = glob(f"{escape(par2_base)}*")
    if par2_files:
        if not force and os.path.exists(par2_base):
            return True
        _remove_par2_files(par2_base, log_file)
    
    log(f"Creating par2 for: {relative_path}", log_file)
    
    os.makedirs(os.path.dirname(par2_base), exist_ok=True)
    
    for attempt in range(PAR2_CREATE_RETRIES):
        try:
            subprocess.run(
                ['par2', 'create', '-B', directory, f'-r{redundancy}', '-n1', par2_base, relative_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
                text=True,
                cwd=directory
            )
            return True
        except subprocess.CalledProcessError as e:
            log(f"Error creating par2 for {relative_path}: {e.stdout}", log_file)
            _remove_par2_files(par2_base, log_file)
            if attempt < PAR2_CREATE_RETRIES - 1:
                delay = min(PAR2_CREATE_BACKOFF_SECONDS * (2 ** attempt), PAR2_CREATE_MAX_BACKOFF_SECONDS)
                log(f"Retrying par2 create for {relative_path} in {delay}s", log_file)
                time.sleep(delay)
            else:
                return False
    return False


def _par2_base_from_parity_file(parity_path: str) -> str:
    """Get par2 base path from any parity file."""
    if PAR2_VOLUME_MARKER in parity_path:
        return parity_path.split(PAR2_VOLUME_MARKER, 1)[0] + PAR2_EXTENSION
    return parity_path


def _cleanup_orphan_par2(
    directory: str,
    database: str,
    existing_files: set[str],
    log_file: str
) -> None:
    """Remove parity files for data files that no longer exist."""
    checked_bases = set()
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
            log(f"Removing orphan par2 for deleted file: {relative_data}", log_file)
            _remove_par2_files(par2_base, log_file)


def verify_repair(file_path: str, directory: str, database: str, log_file: str) -> None:
    """Verify file integrity and repair if needed.
    
    Args:
        file_path: Path to file to verify
        directory: Base directory being protected
        database: Database directory for par2 files
        log_file: Log file path
    """
    relative_path = os.path.relpath(file_path, directory)
    par2_base = os.path.join(database, f"{relative_path}{PAR2_EXTENSION}")
    
    if not os.path.exists(par2_base):
        return
    
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
        except subprocess.CalledProcessError as e:
            log(f"✗ Repair failed: {relative_path}", log_file)
            log(f"  Error: {e.stdout}", log_file)


def scrub_directory(directory: str, database: str, redundancy: int, log_file: str, verify: bool = True) -> None:
    """Scrub directory: create par2 files and optionally verify/repair.
    
    Args:
        directory: Directory to scrub
        database: Database directory for par2 files
        redundancy: Redundancy percentage
        log_file: Log file path
        verify: Whether to verify and repair (False for fast initial creation)
    """
    log("=" * 60, log_file)
    log(f"Scrub started: {datetime.now()}", log_file)
    log(f"Directory: {directory}", log_file)
    log(f"Database: {database}", log_file)
    log(f"Redundancy: {redundancy}%", log_file)
    log(f"Verify: {verify}", log_file)
    log("=" * 60, log_file)
    
    os.makedirs(database, exist_ok=True)
    
    database_path = Path(database).resolve()
    
    existing_files = set()
    
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
            
            if os.path.exists(par2_base):
                try:
                    if os.path.getmtime(file_path) > os.path.getmtime(par2_base) + PAR2_MTIME_TOLERANCE_SECONDS:
                        log(f"Updating par2 for modified file: {relative_path}", log_file)
                        force = True
                except (IOError, OSError) as e:
                    log(f"Error checking par2 timestamps for {relative_path}: {e}", log_file)
                    force = True
            
            create_par2(file_path, directory, database, redundancy, log_file, force=force)
            
            if verify:
                verify_repair(file_path, directory, database, log_file)
    
    _cleanup_orphan_par2(directory, database, existing_files, log_file)
    
    log(f"Scrub completed: {datetime.now()}", log_file)
    log("", log_file)


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
