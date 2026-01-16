#!/usr/bin/env python3
"""Check if sync source and destination paths are mounted before syncing.

This script is called by systemd services as an ExecCondition to ensure
mounts are available before attempting to sync.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from lib.mount_utils import validate_mount_for_sync


def main():
    if len(sys.argv) < 3:
        print("Usage: check_sync_mounts.py <source_path> <destination_path>")
        return 1
    
    source = sys.argv[1]
    destination = sys.argv[2]
    
    if not validate_mount_for_sync(source, "source"):
        return 1
    
    if not validate_mount_for_sync(destination, "destination"):
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
