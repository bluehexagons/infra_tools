"""Directory synchronization with rsync and systemd timers."""

import os
import shlex
import hashlib
from typing import List

from lib.config import SetupConfig
from lib.setup_common import REMOTE_INSTALL_DIR
from .utils import run, is_package_installed
from shared.mount_utils import is_path_under_mnt, get_mount_ancestor
from shared.task_utils import (
    validate_frequency,
    get_timer_calendar,
    escape_systemd_description,
    check_path_on_smb_mount
)


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
    
    if not source.startswith('/'):
        raise ValueError(f"Source path must be absolute: {source}")
    if not destination.startswith('/'):
        raise ValueError(f"Destination path must be absolute: {destination}")
    
    validate_frequency(interval, "interval")
    
    return {
        'source': source,
        'destination': destination,
        'interval': interval
    }


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
    
    path_hash = hashlib.md5(f"{source}:{destination}".encode()).hexdigest()[:8]
    safe_source = source.replace('/', '_').strip('_')
    safe_dest = destination.replace('/', '_').strip('_')
    service_name = f"sync-{safe_source}-to-{safe_dest}-{path_hash}"
    
    if not os.path.exists(source):
        if is_path_under_mnt(source):
            mount_ancestor = get_mount_ancestor(source)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Source {source} is under /mnt but no mount point found")
                print(f"    Skipping directory creation - ensure mount is configured first")
            else:
                print(f"    Creating subdirectory under mount: {source}")
                os.makedirs(source, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(source)}")
        else:
            print(f"  ⚠ Warning: Source directory does not exist: {source}")
            print(f"    Creating directory: {source}")
            os.makedirs(source, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(source)}")
    
    dest_parent = os.path.dirname(destination)
    if dest_parent and not os.path.exists(dest_parent):
        if is_path_under_mnt(dest_parent):
            mount_ancestor = get_mount_ancestor(dest_parent)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Destination parent {dest_parent} is under /mnt but no mount point found")
                print(f"    Skipping directory creation - ensure mount is configured first")
            else:
                print(f"    Creating parent directory under mount: {dest_parent}")
                os.makedirs(dest_parent, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(dest_parent)}")
        else:
            print(f"    Creating parent directory: {dest_parent}")
            os.makedirs(dest_parent, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(dest_parent)}")
    
    escaped_source = escape_systemd_description(source)
    escaped_destination = escape_systemd_description(destination)
    
    source_on_smb = check_path_on_smb_mount(source, config)
    dest_on_smb = check_path_on_smb_mount(destination, config)
    source_under_mnt = is_path_under_mnt(source)
    dest_under_mnt = is_path_under_mnt(destination)
    
    needs_mount_check = source_on_smb or dest_on_smb or source_under_mnt or dest_under_mnt
    
    # Create systemd service file
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    if needs_mount_check:
        # Use Python script for mount checking instead of generated shell script
        check_script = f"{REMOTE_INSTALL_DIR}/check_sync_mounts.py"
        
        service_content = f"""[Unit]
Description=Sync {escaped_source} to {escaped_destination}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
ExecCondition=/usr/bin/python3 {check_script} {shlex.quote(source)} {shlex.quote(destination)}
ExecStart=/usr/bin/rsync -av --delete --exclude='.git' {shlex.quote(source)}/ {shlex.quote(destination)}/
StandardOutput=journal
StandardError=journal
"""
    else:
        service_content = f"""[Unit]
Description=Sync {escaped_source} to {escaped_destination}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
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
