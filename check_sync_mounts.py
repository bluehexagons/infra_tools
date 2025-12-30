#!/usr/bin/env python3
"""Check if sync source and destination paths are mounted before syncing.

This script is called by systemd services as an ExecCondition to ensure
mounts are available before attempting to sync.
"""

import sys
import os

# Add install directory to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.mount_utils import validate_mount_for_sync


def main():
    if len(sys.argv) < 3:
        print("Usage: check_sync_mounts.py <source_path> <destination_path>")
        return 1
    
    source = sys.argv[1]
    destination = sys.argv[2]
    
    # Validate source
    if not validate_mount_for_sync(source, "source"):
        return 1
    
    # Validate destination
    if not validate_mount_for_sync(destination, "destination"):
        return 1
    
    # Both paths are valid
    return 0


if __name__ == "__main__":
    sys.exit(main())
