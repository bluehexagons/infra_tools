"""Swap configuration steps."""

from __future__ import annotations

from lib.config import SetupConfig
from lib.machine_state import can_manage_swap
from lib.remote_utils import run

def get_total_ram_mb() -> int:
    """Get total RAM in MB."""
    result = run("free -m | grep Mem | awk '{print $2}'", capture_output=True)
    try:
        return int(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0

def get_free_disk_mb() -> int:
    """Get free disk space on / in MB."""
    result = run("df -m / | tail -1 | awk '{print $4}'", capture_output=True)
    try:
        return int(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0

def configure_swap(config: SetupConfig) -> None:
    """Configure swap file if not present."""
    
    if not can_manage_swap():
        print("  ✓ Skipping swap configuration (managed by container host)")
        return
    
    result = run("swapon --show", capture_output=True)
    if result.stdout and result.stdout.strip():
        print("  ✓ Swap is already configured")
        return

    if run("test -f /swapfile", check=False).returncode == 0:
        print("  ✓ /swapfile exists but not active? Enabling...")
        run("swapon /swapfile")
        return

    ram_mb = get_total_ram_mb()
    if ram_mb == 0:
        print("  ⚠ Could not detect RAM size, skipping swap setup")
        return

    if ram_mb < 2048:
        swap_size_mb = ram_mb * 2
    elif ram_mb < 8192:
        swap_size_mb = ram_mb
    else:
        swap_size_mb = 4096

    free_disk_mb = get_free_disk_mb()
    if free_disk_mb < (swap_size_mb + 1024): # Leave at least 1GB free after swap
        if free_disk_mb > 2048:
            swap_size_mb = 1024
            print(f"  ⚠ Adjusting swap size to {swap_size_mb}MB due to limited disk space")
        else:
            print(f"  ⚠ Not enough disk space for {swap_size_mb}MB swap (Free: {free_disk_mb}MB). Skipping.")
            return

    print(f"  Creating {swap_size_mb}MB swap file...")
    
    run(f"fallocate -l {swap_size_mb}M /swapfile")
    run("chmod 600 /swapfile")
    run("mkswap /swapfile")
    run("swapon /swapfile")
    
    fstab_entry = "/swapfile none swap sw 0 0"
    run(f"grep -qF '{fstab_entry}' /etc/fstab || echo '{fstab_entry}' >> /etc/fstab")
    
    run("sysctl vm.swappiness=10")
    run("grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf")
    
    print(f"  ✓ Swap configured ({swap_size_mb}MB)")
