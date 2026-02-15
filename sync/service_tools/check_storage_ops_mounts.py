#!/usr/bin/env python3
"""Static mount point validation script for storage operations.

This script checks if all specified mount points are available.
Usage: check_storage_ops_mounts.py <mount_point> [<mount_point> ...]

Exit codes:
  0 - All mount points are available
  1 - One or more mount points are not available
"""

from __future__ import annotations

import os
import sys


def check_mount(mount_point: str) -> bool:
    """Check if a mount point is available."""
    return os.path.ismount(mount_point)


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: check_storage_ops_mounts.py <mount_point> [<mount_point> ...]", file=sys.stderr)
        print("Example: check_storage_ops_mounts.py /mnt/data /mnt/backup", file=sys.stderr)
        return 1
    
    mount_points = sys.argv[1:]
    all_available = True
    
    for mount_point in mount_points:
        if not check_mount(mount_point):
            print(f"Mount point not available: {mount_point}", file=sys.stderr)
            all_available = False
    
    if all_available:
        print("All mount points available")
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
