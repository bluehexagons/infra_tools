"""Storage operations service and timer generation.

This module creates a unified systemd service and timer for all storage
operations (sync and scrub), replacing the previous model of individual
services per task.
"""

from __future__ import annotations

import os
import shlex
from typing import Any

from lib.config import SetupConfig
from lib.setup_common import REMOTE_INSTALL_DIR
from lib.remote_utils import run, is_dry_run
from lib.systemd_service import cleanup_service
from lib.task_utils import (
    get_mount_points_from_config,
    has_mount_paths,
)


SERVICE_NAME = "storage-ops"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"
TIMER_FILE = f"/etc/systemd/system/{SERVICE_NAME}.timer"


def schedule_storage_ops_update(delay_minutes: int = 0, immediate: bool = True) -> None:
    """Schedule and/or run storage operations after setup.
    
    Args:
        delay_minutes: Schedule a delayed run via timer (0 = don't schedule delayed run)
        immediate: Run the service immediately in background (default True)
    
    By default, this triggers an immediate background run so the first sync/scrub
    happens right away. This can be disabled for testing or if you want only
    scheduled runs.
    
    To check status:
      - journalctl -u storage-ops.service -f
      - systemctl status storage-ops.service
    """
    if immediate:
        # Trigger immediate run in background (non-blocking)
        # Use systemd-run to ensure proper service isolation and logging
        result = run(
            f"systemd-run --unit=storage-ops-immediate --no-block "
            f"/usr/bin/systemctl start {SERVICE_NAME}.service",
            check=False,
        )
        if result == 0:
            print(f"    ✓ Triggered immediate storage-ops run in background")
            print(f"    ℹ Check progress: journalctl -u {SERVICE_NAME}.service -f")
        else:
            print(f"    ⚠ Failed to trigger immediate run (will rely on scheduled timer)")
    
    if delay_minutes > 0:
        # Also schedule a delayed run as backup
        run(
            " ".join(
                [
                    "systemd-run",
                    "--unit=storage-ops-delayed-update",
                    "--timer-property=AccuracySec=1s",
                    "--on-active",
                    f"{delay_minutes}m",
                    f"/usr/bin/systemctl start {SERVICE_NAME}.service",
                ]
            ),
            check=False,
        )
        print(f"    ✓ Also scheduled backup run in ~{delay_minutes} minute(s)")
    
    print(f"    ℹ To trigger manually: systemctl start {SERVICE_NAME}.service")


def create_storage_ops_service(config: SetupConfig, **_kwargs: Any) -> None:
    """Create unified storage operations service and timer.

    This function creates a single systemd service and timer that will
    orchestrate all sync and scrub operations defined in the config.
    The service reads specs from machine state and executes them in order.
    """
    if not config.sync_specs and not config.scrub_specs:
        print("  No storage operations configured, skipping unified service creation")
        return
    if is_dry_run():
        print("  [DRY-RUN] Skipping unified storage operations service creation")
        return

    print("\n  Creating unified storage operations service...")

    # Clean up any existing service
    cleanup_service(SERVICE_NAME)
    
    # Lock files are automatically cleaned up on reboot (stored in /run/lock tmpfs)
    # Don't remove them during service creation as they may belong to running operations

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
    run(f"systemctl --no-pager status {SERVICE_NAME}.timer", check=False)

    print(f"    ✓ Storage operations timer started")
    print(f"    ℹ Run 'systemctl status {SERVICE_NAME}.timer' to check status")


def generate_mount_check_condition(config: SetupConfig) -> str:
    """Generate ExecCondition for mount validation.

    Returns a systemd ExecCondition line that validates all configured
    mount points are available before running operations.
    """
    mount_points = get_mount_points_from_config(config)

    if not mount_points:
        return ""

    # Use static script with mount points as arguments
    check_script_path = f"{REMOTE_INSTALL_DIR}/sync/service_tools/check_storage_ops_mounts.py"
    mount_args = " ".join(shlex.quote(mp) for mp in sorted(mount_points))

    return f"ExecCondition=/usr/bin/python3 {shlex.quote(check_script_path)} {mount_args}\n"
