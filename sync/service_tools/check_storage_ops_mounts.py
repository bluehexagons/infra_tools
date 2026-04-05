#!/usr/bin/env python3
"""Static mount point validation script for storage operations.

This script checks if all specified mount points are available.
Usage: check_storage_ops_mounts.py <mount_point> [<mount_point> ...]

Exit codes:
  0 - All mount points are available
  1 - One or more mount points are not available
"""

from __future__ import annotations

from logging import ERROR, INFO, WARNING, Logger
import os
import sys

from lib.logging_utils import get_service_logger, log_event


def check_mount(mount_point: str) -> bool:
    """Check if a mount point is available."""
    return os.path.ismount(mount_point)


def main(argv: list[str] | None = None, logger: Logger | None = None) -> int:
    """Main entry point."""
    if argv is None:
        argv = sys.argv[1:]
    if logger is None:
        logger = get_service_logger(
            'check_storage_ops_mounts',
            'sync',
            use_syslog=False,
            console_output=False,
        )

    if not argv:
        log_event(logger, "Mount check invocation missing arguments", level=WARNING)
        print("Usage: check_storage_ops_mounts.py <mount_point> [<mount_point> ...]", file=sys.stderr)
        print("Example: check_storage_ops_mounts.py /mnt/data /mnt/backup", file=sys.stderr)
        return 1
    
    mount_points = argv
    all_available = True
    
    for mount_point in mount_points:
        if not check_mount(mount_point):
            log_event(logger, "Mount point unavailable", level=ERROR, mount_point=mount_point)
            print(f"Mount point not available: {mount_point}", file=sys.stderr)
            all_available = False
    
    if all_available:
        log_event(logger, "All mount points available", level=INFO, mount_count=len(mount_points))
        print("All mount points available")
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
