#!/usr/bin/env python3
"""Check if scrub directory and database paths are mounted before scrubbing.

This script is called by systemd services as an ExecCondition to ensure
mounts are available before attempting to scrub.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from lib.mount_utils import validate_mount_for_sync


def main():
    if len(sys.argv) < 3:
        print("Usage: check_scrub_mounts.py <directory_path> <database_path>")
        return 1
    
    directory = sys.argv[1]
    database_path = sys.argv[2]
    
    if not validate_mount_for_sync(directory, "directory"):
        return 1
    
    if not validate_mount_for_sync(database_path, "database"):
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
