"""Swap configuration steps."""

import os
import re
from .utils import run

def get_total_ram_mb(run_func) -> int:
    """Get total RAM in MB."""
    result = run_func("free -m | grep Mem | awk '{print $2}'")
    try:
        return int(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0

def get_free_disk_mb(run_func) -> int:
    """Get free disk space on / in MB."""
    result = run_func("df -m / | tail -1 | awk '{print $4}'")
    try:
        return int(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0

def configure_swap(username: str, run_func=run, **kwargs) -> None:
    """Configure swap file if not present."""
    
    # Check if swap is already active
    result = run_func("swapon --show")
    if result.stdout and result.stdout.strip():
        print("  ✓ Swap is already configured")
        return

    # Check if /swapfile exists
    if run_func("test -f /swapfile", check=False).returncode == 0:
        print("  ✓ /swapfile exists but not active? Enabling...")
        run_func("swapon /swapfile")
        return

    ram_mb = get_total_ram_mb(run_func)
    if ram_mb == 0:
        print("  ⚠ Could not detect RAM size, skipping swap setup")
        return

    # Calculate desired swap size
    if ram_mb < 2048:
        swap_size_mb = ram_mb * 2
    elif ram_mb < 8192:
        swap_size_mb = ram_mb
    else:
        swap_size_mb = 4096

    # Check disk space
    free_disk_mb = get_free_disk_mb(run_func)
    if free_disk_mb < (swap_size_mb + 1024): # Leave at least 1GB free after swap
        if free_disk_mb > 2048:
            swap_size_mb = 1024
            print(f"  ⚠ Adjusting swap size to {swap_size_mb}MB due to limited disk space")
        else:
            print(f"  ⚠ Not enough disk space for {swap_size_mb}MB swap (Free: {free_disk_mb}MB). Skipping.")
            return

    print(f"  Creating {swap_size_mb}MB swap file...")
    
    # Create swap file
    run_func(f"fallocate -l {swap_size_mb}M /swapfile")
    run_func("chmod 600 /swapfile")
    run_func("mkswap /swapfile")
    run_func("swapon /swapfile")
    
    # Add to fstab
    fstab_entry = "/swapfile none swap sw 0 0"
    run_func(f"grep -qF '{fstab_entry}' /etc/fstab || echo '{fstab_entry}' >> /etc/fstab")
    
    # Adjust swappiness (optional, but good practice)
    run_func("sysctl vm.swappiness=10")
    run_func("grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf")
    
    print(f"  ✓ Swap configured ({swap_size_mb}MB)")
