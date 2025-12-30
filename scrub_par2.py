#!/usr/bin/env python3
"""Par2 scrub operations for data integrity checking.

This script creates par2 parity files, verifies files, and repairs corrupted files.
"""

import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime


def log(message: str, log_file: str) -> None:
    """Append message to log file."""
    try:
        with open(log_file, 'a') as f:
            f.write(f"{message}\n")
    except (IOError, OSError) as e:
        print(f"Error writing to log {log_file}: {e}", file=sys.stderr)


def create_par2(file_path: str, directory: str, database: str, redundancy: int, log_file: str) -> bool:
    """Create par2 parity file if it doesn't exist.
    
    Args:
        file_path: Path to file to protect
        directory: Base directory being protected
        database: Database directory for par2 files
        redundancy: Redundancy percentage
        log_file: Log file path
        
    Returns:
        True if created or already exists, False on error
    """
    relative_path = os.path.relpath(file_path, directory)
    par2_base = os.path.join(database, f"{relative_path}.par2")
    
    if os.path.exists(par2_base):
        return True
    
    log(f"Creating par2 for: {relative_path}", log_file)
    
    os.makedirs(os.path.dirname(par2_base), exist_ok=True)
    
    try:
        subprocess.run(
            ['par2', 'create', f'-r{redundancy}', '-n1', par2_base, file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            text=True
        )
        return True
    except subprocess.CalledProcessError as e:
        log(f"Error creating par2 for {relative_path}: {e.stdout}", log_file)
        return False


def verify_repair(file_path: str, directory: str, database: str, log_file: str) -> None:
    """Verify file integrity and repair if needed.
    
    Args:
        file_path: Path to file to verify
        directory: Base directory being protected
        database: Database directory for par2 files
        log_file: Log file path
    """
    relative_path = os.path.relpath(file_path, directory)
    par2_base = os.path.join(database, f"{relative_path}.par2")
    
    if not os.path.exists(par2_base):
        return
    
    log(f"Verifying: {relative_path}", log_file)
    
    try:
        subprocess.run(
            ['par2', 'verify', par2_base],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True,
            text=True
        )
    except subprocess.CalledProcessError:
        log(f"Verification failed for: {relative_path}", log_file)
        log("Attempting repair...", log_file)
        
        try:
            subprocess.run(
                ['par2', 'repair', par2_base],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
                text=True
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
    
    directory_path = Path(directory).resolve()
    database_path = Path(database).resolve()
    
    for root, dirs, files in os.walk(directory):
        root_path = Path(root).resolve()
        
        if root_path == database_path or database_path in root_path.parents:
            continue
        
        dirs[:] = [d for d in dirs if not (root_path / d).resolve() == database_path 
                   and database_path not in (root_path / d).resolve().parents]
        
        for filename in files:
            file_path = os.path.join(root, filename)
            
            create_par2(file_path, directory, database, redundancy, log_file)
            
            if verify:
                verify_repair(file_path, directory, database, log_file)
    
    log(f"Scrub completed: {datetime.now()}", log_file)
    log("", log_file)


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
