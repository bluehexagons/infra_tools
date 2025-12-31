#!/usr/bin/env python3
"""Check if scrub directory and database paths are mounted before scrubbing.

This script is called by systemd services as an ExecCondition to ensure
mounts are available before attempting to scrub.
"""

import sys
import os

# Add parent directory to path so we can import lib modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from lib.mount_utils import validate_mount_for_sync


def main():
    if len(sys.argv) < 3:
        print("Usage: check_scrub_mounts.py <directory_path> <database_path>")
        return 1
    
    directory = sys.argv[1]
    database_path = sys.argv[2]
    
    # Validate directory
    if not validate_mount_for_sync(directory, "directory"):
        return 1
    
    # Validate database path
    if not validate_mount_for_sync(database_path, "database"):
        return 1
    
    # Both paths are valid
    return 0


if __name__ == "__main__":
    sys.exit(main())
