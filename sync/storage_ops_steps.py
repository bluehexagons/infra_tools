"""Storage operations service and timer generation.

This module creates a unified systemd service and timer for all storage
operations (sync and scrub), replacing the previous model of individual
services per task.
"""

from __future__ import annotations

import os
import shlex
from typing import Any, Optional

from lib.config import SetupConfig
from lib.setup_common import REMOTE_INSTALL_DIR
from lib.remote_utils import run
from lib.systemd_service import cleanup_service


SERVICE_NAME = "storage-ops"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"
TIMER_FILE = f"/etc/systemd/system/{SERVICE_NAME}.timer"


def has_mount_paths(config: SetupConfig) -> bool:
    """Check if any sync or scrub spec involves mounted paths."""
    from lib.mount_utils import is_path_under_mnt
    from lib.task_utils import check_path_on_smb_mount
    
    # Check sync specs
    for sync_spec in config.sync_specs:
        if len(sync_spec) >= 2:
            source, destination = sync_spec[0], sync_spec[1]
            if (is_path_under_mnt(source) or is_path_under_mnt(destination) or
                check_path_on_smb_mount(source, config) or check_path_on_smb_mount(destination, config)):
                return True
    
    # Check scrub specs
    for scrub_spec in config.scrub_specs:
        if len(scrub_spec) >= 2:
            directory, database = scrub_spec[0], scrub_spec[1]
            if (is_path_under_mnt(directory) or is_path_under_mnt(database) or
                check_path_on_smb_mount(directory, config) or check_path_on_smb_mount(database, config)):
                return True
    
    return False


def create_storage_ops_service(config: SetupConfig, **_kwargs: Any) -> None:
    """Create unified storage operations service and timer.
    
    This function creates a single systemd service and timer that will
    orchestrate all sync and scrub operations defined in the config.
    The service reads specs from machine state and executes them in order.
    """
    if not config.sync_specs and not config.scrub_specs:
        print("  No storage operations configured, skipping unified service creation")
        return
    
    print("\n  Creating unified storage operations service...")
    
    # Clean up any existing service
    cleanup_service(SERVICE_NAME)
    
    # Create required directories
    os.makedirs("/var/lib/storage-ops", exist_ok=True)
    os.makedirs("/var/log/storage-ops", exist_ok=True)
    
    # Determine if mount checking is needed
    needs_mount_check = has_mount_paths(config)
    
    # Paths
    orchestrator_script = f"{REMOTE_INSTALL_DIR}/sync/service_tools/storage_ops.py"
    
    # Build service file content
    exec_condition = ""
    if needs_mount_check:
        # Create a mount check script that validates all configured paths
        exec_condition = generate_mount_check_condition(config)
    
    service_content = f"""[Unit]
Description=Unified storage operations (sync, scrub, parity)
After=local-fs.target network.target
Documentation=https://github.com/anomalyco/infra_tools/blob/main/docs/STORAGE.md

[Service]
Type=oneshot
User=root
Group=root
{exec_condition}ExecStart=/usr/bin/python3 {shlex.quote(orchestrator_script)}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=storage-ops
TimeoutStartSec=14400
# Allow the service to run for up to 4 hours

[Install]
WantedBy=multi-user.target
"""
    
    # Write service file
    with open(SERVICE_FILE, 'w') as f:
        f.write(service_content)
    
    print(f"    ✓ Created service: {SERVICE_NAME}.service")
    
    # Build timer file content - run hourly at :00
    timer_content = f"""[Unit]
Description=Timer for unified storage operations

[Timer]
OnCalendar=*-*-* *:00:00
Persistent=true
AccuracySec=1m
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
"""
    
    # Write timer file
    with open(TIMER_FILE, 'w') as f:
        f.write(timer_content)
    
    print(f"    ✓ Created timer: {SERVICE_NAME}.timer (hourly)")
    
    # Reload systemd and enable/start timer
    run("systemctl daemon-reload")
    run(f"systemctl enable {SERVICE_NAME}.timer")
    run(f"systemctl start {SERVICE_NAME}.timer")
    
    print(f"    ✓ Storage operations timer started")
    print(f"    ℹ Run 'systemctl status {SERVICE_NAME}.timer' to check status")


def generate_mount_check_condition(config: SetupConfig) -> str:
    """Generate ExecCondition for mount validation.
    
    Returns a systemd ExecCondition line that validates all configured
    mount points are available before running operations.
    """
    from lib.mount_utils import is_path_under_mnt
    from lib.task_utils import check_path_on_smb_mount
    
    mount_points: set[str] = set()
    
    # Collect all unique mount points from sync specs
    for sync_spec in config.sync_specs:
        if len(sync_spec) >= 2:
            source, destination = sync_spec[0], sync_spec[1]
            for path in [source, destination]:
                if is_path_under_mnt(path):
                    mount_point = get_mount_point(path)
                    if mount_point:
                        mount_points.add(mount_point)
    
    # Collect all unique mount points from scrub specs
    for scrub_spec in config.scrub_specs:
        if len(scrub_spec) >= 2:
            directory, database = scrub_spec[0], scrub_spec[1]
            for path in [directory, database]:
                if is_path_under_mnt(path):
                    mount_point = get_mount_point(path)
                    if mount_point:
                        mount_points.add(mount_point)
    
    if not mount_points:
        return ""
    
    # Create mount check script
    check_script_content = generate_mount_check_script(mount_points)
    check_script_path = f"{REMOTE_INSTALL_DIR}/sync/service_tools/check_storage_ops_mounts.py"
    
    with open(check_script_path, 'w') as f:
        f.write(check_script_content)
    
    # Make executable
    os.chmod(check_script_path, 0o755)
    
    return f"ExecCondition=/usr/bin/python3 {shlex.quote(check_script_path)}\n"


def get_mount_point(path: str) -> Optional[str]:
    """Get the mount point for a given path."""
    from lib.mount_utils import get_mount_ancestor
    
    mount_ancestor = get_mount_ancestor(path)
    if mount_ancestor:
        return mount_ancestor
    
    # Fallback: check if the path itself is a mount point
    if os.path.ismount(path):
        return path
    
    return None


def generate_mount_check_script(mount_points: set[str]) -> str:
    """Generate a Python script to validate mount points."""
    mount_list = sorted(list(mount_points))
    mount_checks = "\n    ".join([
        f'("{mp}", os.path.ismount("{mp}"))' for mp in mount_list
    ])
    
    return f'''#!/usr/bin/env python3
"""Mount point validation for storage operations."""

import os
import sys

def check_mounts():
    """Check if all required mount points are available."""
    mounts = [
        {mount_checks}
    ]
    
    all_available = True
    for mount_point, is_mounted in mounts:
        if not is_mounted:
            print(f"Mount point not available: {{mount_point}}", file=sys.stderr)
            all_available = False
    
    if all_available:
        print("All mount points available")
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(check_mounts())
'''

