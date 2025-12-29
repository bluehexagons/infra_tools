"""Mount validation utilities for checking if paths are on mounted filesystems."""

import os
import subprocess
from typing import Optional


def is_path_under_mnt(path: str) -> bool:
    """Check if path is under /mnt directory."""
    return path.startswith('/mnt/')


def get_mount_ancestor(path: str) -> Optional[str]:
    """Find the mount point ancestor of a path.
    
    Returns the path itself if it's a mount point, or the closest
    parent directory that is a mount point. Returns None if
    no mount point found.
    """
    current = path
    while current and current != '/':
        result = subprocess.run(
            ['mountpoint', '-q', current],
            capture_output=True
        )
        if result.returncode == 0:
            return current
        current = os.path.dirname(current)
    return None


def is_path_mounted(path: str) -> bool:
    """Check if a path or its parent directories are on a mounted filesystem.
    
    Args:
        path: Path to check
        
    Returns:
        True if path is on a mounted filesystem, False otherwise
    """
    return get_mount_ancestor(path) is not None


def validate_mount_for_sync(path: str, path_name: str = "path") -> bool:
    """Validate that a path is mounted if it's under /mnt or should be mounted.
    
    Args:
        path: Path to validate
        path_name: Description of path for error messages (e.g., "source", "destination")
        
    Returns:
        True if validation passes, False otherwise
        
    Prints error messages to stderr if validation fails.
    """
    # Check if path itself is a mount point
    result = subprocess.run(
        ['mountpoint', '-q', path],
        capture_output=True
    )
    
    if result.returncode == 0:
        # Path is a mount point, all good
        return True
    
    # Check if a parent directory is a mount point
    mount_ancestor = get_mount_ancestor(path)
    
    if mount_ancestor:
        # Parent is mounted, path is safe to use
        return True
    
    # No mount point found - this is an error if under /mnt
    if is_path_under_mnt(path):
        print(f"Error: {path_name.capitalize()} path {path} is not on a mounted filesystem", flush=True)
        return False
    
    # Not under /mnt and no mount requirement - allow it
    # (could be a local filesystem path)
    return True
