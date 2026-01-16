"""Enhanced disk space management utilities extending swap_steps.py patterns."""

from __future__ import annotations
import shutil

# Note: os/subprocess/Path not used directly in this module - removed to keep strict checks clean


def get_free_disk_mb(path: str = "/") -> int:
    """Get free disk space in MB for any path.
    
    Args:
        path: Path to check disk space for (default: /)
        
    Returns:
        int: Free disk space in MB, 0 if error
    """
    try:
        stat = shutil.disk_usage(path)
        return stat.free // (1024 * 1024)  # Convert to MB
    except (OSError, AttributeError) as e:
        print(f"Error getting disk space for {path}: {e}")
        return 0


def get_total_disk_mb(path: str = "/") -> int:
    """Get total disk space in MB for any path.
    
    Args:
        path: Path to check disk space for (default: /)
        
    Returns:
        int: Total disk space in MB, 0 if error
    """
    try:
        stat = shutil.disk_usage(path)
        return stat.total // (1024 * 1024)  # Convert to MB
    except (OSError, AttributeError) as e:
        print(f"Error getting total disk space for {path}: {e}")
        return 0


def get_disk_usage_details(path: str) -> dict[str, int]:
    """Get detailed disk usage information.
    
    Args:
        path: Path to analyze
        
    Returns:
        Dict with disk usage details in MB
    """
    try:
        stat = shutil.disk_usage(path)
        return {
            'total_mb': stat.total // (1024 * 1024),
            'used_mb': stat.used // (1024 * 1024),
            'free_mb': stat.free // (1024 * 1024),
            'usage_percent': int((stat.used / stat.total) * 100) if stat.total > 0 else 0
        }
    except (OSError, AttributeError) as e:
        print(f"Error getting disk usage for {path}: {e}")
        return {'total_mb': 0, 'used_mb': 0, 'free_mb': 0, 'usage_percent': 0}


def check_disk_space_threshold(path: str, warning_threshold: int = 80, critical_threshold: int = 90) -> tuple[str, int]:
    """Check disk space against thresholds.
    
    Args:
        path: Path to check
        warning_threshold: Warning threshold percentage (default: 80%)
        critical_threshold: Critical threshold percentage (default: 90%)
        
    Returns:
        tuple of (status, usage_percent) where status is 'ok', 'warning', or 'critical'
    """
    details = get_disk_usage_details(path)
    usage_percent = details['usage_percent']
    
    if usage_percent >= critical_threshold:
        return 'critical', usage_percent
    elif usage_percent >= warning_threshold:
        return 'warning', usage_percent
    else:
        return 'ok', usage_percent


def estimate_operation_duration(operation_type: str, data_size_mb: int) -> int:
    """Estimate operation duration in minutes.
    
    Args:
        operation_type: Type of operation ('sync', 'scrub', 'par2')
        data_size_mb: Size of data in MB
        
    Returns:
        int: Estimated duration in minutes
    """
    # Throughput estimates in MB/minute (conservative estimates)
    throughput = {
        'sync': 100,    # Local sync: ~100MB/min
        'scrub': 50,    # Scrubbing: ~50MB/min (more I/O intensive)
        'par2': 25,     # PAR2 creation: ~25MB/min (CPU intensive)
    }
    
    mb_per_min = throughput.get(operation_type, 50)
    estimated_minutes = max(1, data_size_mb // mb_per_min)
    
    # Add overhead for setup and cleanup
    overhead = {
        'sync': 5,
        'scrub': 10,
        'par2': 15,
    }
    
    return estimated_minutes + overhead.get(operation_type, 10)


def get_multiple_paths_usage(paths: list[str]) -> dict[str, dict[str, int]]:
    """Get disk usage for multiple paths.
    
    Args:
        paths: List of paths to check
        
    Returns:
        Dict mapping path to usage details
    """
    results: dict[str, dict[str, int]] = {}
    for path in paths:
        results[path] = get_disk_usage_details(path)
    return results