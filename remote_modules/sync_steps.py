"""Directory synchronization with rsync and systemd timers."""

import os
import shlex
import hashlib
from typing import List

from lib.config import SetupConfig
from .utils import run, is_package_installed


def install_rsync(config: SetupConfig) -> None:
    """Install rsync if not already installed."""
    if is_package_installed("rsync"):
        print("  ✓ rsync already installed")
        return
    
    run("apt-get install -y -qq rsync")
    print("  ✓ rsync installed")


def parse_sync_spec(sync_spec: List[str]) -> dict:
    """Parse sync specification.
    
    Args:
        sync_spec: [source_path, destination_path, interval]
        
    Returns:
        dict with 'source', 'destination', 'interval'
    """
    if len(sync_spec) != 3:
        raise ValueError(f"Invalid sync spec: expected 3 arguments, got {len(sync_spec)}")
    
    source, destination, interval = sync_spec
    
    # Validate that paths are absolute
    if not source.startswith('/'):
        raise ValueError(f"Source path must be absolute: {source}")
    if not destination.startswith('/'):
        raise ValueError(f"Destination path must be absolute: {destination}")
    
    # Validate interval
    valid_intervals = ['hourly', 'daily', 'weekly', 'monthly']
    if interval not in valid_intervals:
        raise ValueError(f"Invalid interval '{interval}'. Must be one of: {', '.join(valid_intervals)}")
    
    return {
        'source': source,
        'destination': destination,
        'interval': interval
    }


def _escape_systemd_description(value: str) -> str:
    """Escape value for safe use in a systemd Description field."""
    return value.replace("\\", "\\\\").replace("\n", " ").replace('"', "'")


def get_timer_calendar(interval: str) -> str:
    """Get systemd timer OnCalendar value for the given interval.
    
    Args:
        interval: 'hourly', 'daily', 'weekly', or 'monthly'
        
    Returns:
        OnCalendar string for systemd timer
    """
    calendars = {
        'hourly': '*-*-* *:00:00',  # Every hour on the hour
        'daily': '*-*-* 02:00:00',   # Daily at 2 AM
        'weekly': 'Mon *-*-* 02:00:00',  # Monday at 2 AM
        'monthly': '*-*-01 02:00:00'  # First day of month at 2 AM
    }
    return calendars.get(interval, '*-*-* 02:00:00')


def create_sync_service(config: SetupConfig, sync_spec: List[str] = None, **_) -> None:
    """Create rsync systemd service and timer for directory synchronization.
    
    Args:
        config: SetupConfig object
        sync_spec: [source_path, destination_path, interval]
    """
    sync_config = parse_sync_spec(sync_spec)
    
    source = sync_config['source']
    destination = sync_config['destination']
    interval = sync_config['interval']
    
    # Create a unique name for the service using hash to avoid collisions
    # For example, /home/user and /home_user would otherwise both become 'home_user'
    path_hash = hashlib.md5(f"{source}:{destination}".encode()).hexdigest()[:8]
    safe_source = source.replace('/', '_').strip('_')
    safe_dest = destination.replace('/', '_').strip('_')
    service_name = f"sync-{safe_source}-to-{safe_dest}-{path_hash}"
    
    # Ensure source directory exists
    if not os.path.exists(source):
        print(f"  ⚠ Warning: Source directory does not exist: {source}")
        print(f"    Creating directory: {source}")
        os.makedirs(source, exist_ok=True)
        run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(source)}")
    
    # Ensure destination parent directory exists
    dest_parent = os.path.dirname(destination)
    if dest_parent and not os.path.exists(dest_parent):
        print(f"    Creating parent directory: {dest_parent}")
        os.makedirs(dest_parent, exist_ok=True)
        run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(dest_parent)}")
    
    # Escape paths for systemd description
    escaped_source = _escape_systemd_description(source)
    escaped_destination = _escape_systemd_description(destination)
    
    # Create systemd service file
    service_file = f"/etc/systemd/system/{service_name}.service"
    service_content = f"""[Unit]
Description=Sync {escaped_source} to {escaped_destination}
After=local-fs.target

[Service]
Type=oneshot
User={config.username}
Group={config.username}
ExecStart=/usr/bin/rsync -av --delete --exclude='.git' {shlex.quote(source)}/ {shlex.quote(destination)}/
StandardOutput=journal
StandardError=journal
"""
    
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    print(f"  ✓ Created service: {service_name}.service")
    
    # Create systemd timer file
    timer_file = f"/etc/systemd/system/{service_name}.timer"
    calendar = get_timer_calendar(interval)
    
    timer_content = f"""[Unit]
Description=Timer for syncing {escaped_source} to {escaped_destination} ({interval})
Requires={service_name}.service

[Timer]
OnCalendar={calendar}
Persistent=true
AccuracySec=1m

[Install]
WantedBy=timers.target
"""
    
    with open(timer_file, 'w') as f:
        f.write(timer_content)
    
    print(f"  ✓ Created timer: {service_name}.timer ({interval})")
    
    # Reload systemd, enable and start the timer
    run("systemctl daemon-reload")
    run(f"systemctl enable {shlex.quote(service_name)}.timer")
    run(f"systemctl start {shlex.quote(service_name)}.timer")
    
    print(f"  ✓ Enabled and started timer")
    
    # Show timer status
    result = run(f"systemctl list-timers {shlex.quote(service_name)}.timer --no-pager", check=False)
    if result.returncode == 0:
        print(f"  ℹ Timer status:")
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                print(f"    {line}")
    
    # Perform initial sync
    print(f"  ℹ Performing initial sync...")
    result = run(f"systemctl start {shlex.quote(service_name)}.service", check=False)
    if result.returncode == 0:
        print(f"  ✓ Initial sync completed")
    else:
        print(f"  ⚠ Warning: Initial sync may have failed. Check: journalctl -u {shlex.quote(service_name)}.service")
    
    print(f"  ✓ Sync configured: {source} → {destination} ({interval})")
