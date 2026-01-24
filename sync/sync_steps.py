"""Directory synchronization with rsync and systemd timers."""

from __future__ import annotations

import os
import shlex
import hashlib
import time
from typing import Optional, Any

from lib.config import SetupConfig
from lib.setup_common import REMOTE_INSTALL_DIR
from lib.remote_utils import run, is_package_installed
from lib.mount_utils import validate_mount_for_sync, validate_smb_connectivity, is_path_under_mnt, get_mount_ancestor
from lib.disk_utils import get_disk_usage_details
from lib.validation import validate_filesystem_path, validate_service_name_uniqueness
from lib.operation_log import create_operation_logger
from lib.transaction import create_transaction
from lib.service_manager import ServiceManager
from lib.task_utils import (
    validate_frequency,
    get_timer_calendar,
    escape_systemd_description,
    check_path_on_smb_mount
)


def install_rsync(config: SetupConfig) -> None:
    if is_package_installed("rsync"):
        print("  ✓ rsync already installed")
        return
    
    run("apt-get install -y -qq rsync")
    print("  ✓ rsync installed")

def parse_sync_spec(sync_spec: list[str]) -> dict[str, Any]:
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

def create_sync_service(config: SetupConfig, sync_spec: Optional[list[str]] = None, **_ : Any) -> None:
    if not sync_spec:
        raise ValueError("sync_spec is required")
    
    sync_config = parse_sync_spec(sync_spec)
    
    source = sync_config['source']
    destination = sync_config['destination']
    interval = sync_config['interval']
    
    logger = create_operation_logger("sync", source=source, destination=destination, interval=interval)
    transaction = create_transaction(f"sync_{int(time.time())}", logger, timeout_seconds=1800)
    
    try:
        transaction.add_validation_step(
            lambda: validate_filesystem_path(source, must_exist=True, check_writable=False),
            f"Validate source path: {source}",
            "validate_source"
        )
        transaction.add_validation_step(
            lambda: validate_filesystem_path(destination, check_writable=True),
            f"Validate destination path: {destination}",
            "validate_destination"
        )
        transaction.add_validation_step(
            lambda: validate_mount_for_sync(source, "source"),
            f"Validate source mount: {source}",
            "validate_source_mount"
        )
        transaction.add_validation_step(
            lambda: validate_mount_for_sync(destination, "destination"),
            f"Validate destination mount: {destination}",
            "validate_destination_mount"
        )
        
        if not transaction.execute():
            logger.log_error("validation_failed", "Pre-sync validation failed")
            transaction.rollback("Validation failed")
            return
        
        logger.log_metric("validation_success", True)
        
        path_hash = hashlib.md5(f"{source}:{destination}".encode()).hexdigest()[:8]
        safe_source = source.replace('/', '_').strip('_')
        safe_dest = destination.replace('/', '_').strip('_')
        service_name = f"sync-{safe_source}-to-{safe_dest}-{path_hash}"
        
        if not validate_service_name_uniqueness(service_name, []):
            service_manager = ServiceManager(config)
            existing_services = service_manager.list_backup_services()
            if not validate_service_name_uniqueness(service_name, existing_services):
                raise ValueError(f"Service name '{service_name}' conflicts with existing service")
        
        logger.log_step("service_name_validation", "completed", f"Validated service name: {service_name}")
        
    except Exception as e:
        logger.log_error("sync_setup_error", str(e))
        if transaction:
            transaction.rollback(str(e))
        raise
    
    if not os.path.exists(source):
        if is_path_under_mnt(source):
            mount_ancestor = get_mount_ancestor(source)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Source {source} is under /mnt but no mount point found")
            else:
                os.makedirs(source, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(source)}")
        else:
            os.makedirs(source, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(source)}")
    
    dest_parent = os.path.dirname(destination)
    if dest_parent and not os.path.exists(dest_parent):
        if is_path_under_mnt(dest_parent):
            mount_ancestor = get_mount_ancestor(dest_parent)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Destination parent {dest_parent} is under /mnt but no mount point found")
            else:
                os.makedirs(dest_parent, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(dest_parent)}")
        else:
            os.makedirs(dest_parent, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(dest_parent)}")
    
    escaped_source = escape_systemd_description(source)
    escaped_destination = escape_systemd_description(destination)
    
    source_on_smb = check_path_on_smb_mount(source, config)
    dest_on_smb = check_path_on_smb_mount(destination, config)
    source_under_mnt = is_path_under_mnt(source)
    dest_under_mnt = is_path_under_mnt(destination)
    
    needs_mount_check = source_on_smb or dest_on_smb or source_under_mnt or dest_under_mnt
    
    if source_on_smb or dest_on_smb:
        logger.log_step("mount_validation_enhanced", "started", "Performing enhanced mount validation")
        if source_on_smb:
            logger.log_metric("source_smb_connectivity", validate_smb_connectivity(source))
        if dest_on_smb:
            logger.log_metric("destination_smb_connectivity", validate_smb_connectivity(destination))
        logger.log_step("mount_validation_enhanced", "completed", "Enhanced mount validation completed")
    
    service_file = f"/etc/systemd/system/{service_name}.service"
    check_script = f"{REMOTE_INSTALL_DIR}/sync/service_tools/check_sync_mounts.py"
    
    exec_condition = f"ExecCondition=/usr/bin/python3 {check_script} {shlex.quote(source)} {shlex.quote(destination)}" if needs_mount_check else ""
    
    service_content = f"""[Unit]
Description=Sync {escaped_source} to {escaped_destination}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
{exec_condition}
ExecStart=/usr/bin/rsync -av --delete --delete-delay --partial --exclude='.git' {shlex.quote(source)}/ {shlex.quote(destination)}/
StandardOutput=journal
StandardError=journal
"""
    
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    print(f"  ✓ Created service: {service_name}.service")
    
    timer_file = f"/etc/systemd/system/{service_name}.timer"
    calendar = get_timer_calendar(interval, hour_offset=2)
    
    timer_content = f"""[Unit]
Description=Timer for syncing {escaped_source} to {escaped_destination} ({interval})

[Timer]
OnCalendar={calendar}
Persistent=true
AccuracySec=1m
Unit={service_name}.service

[Install]
WantedBy=timers.target
"""
    
    with open(timer_file, 'w') as f:
        f.write(timer_content)
    
    print(f"  ✓ Created timer: {service_name}.timer ({interval})")
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {shlex.quote(service_name)}.timer")
    run(f"systemctl start {shlex.quote(service_name)}.timer")
    
    def perform_initial_sync():
        result = run(f"systemctl start {shlex.quote(service_name)}.service", check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Initial sync failed: {shlex.quote(service_name)}.service")
        return True
    
    try:
        transaction.add_step(perform_initial_sync, lambda: run(f"systemctl stop {shlex.quote(service_name)}.service", check=False), "Initial sync", "initial_sync")
        
        if not transaction.execute():
            logger.log_error("initial_sync_failed", "Initial sync failed")
            transaction.rollback("Initial sync failed")
        else:
            logger.log_step("initial_sync", "completed", "Initial sync successful")
        
        logger.complete("completed", "Sync service configured")
        
    except Exception as e:
        logger.log_error("initial_sync_error", str(e))
        if transaction:
            transaction.rollback(str(e))
    
    source_disk = get_disk_usage_details(source)
    dest_disk = get_disk_usage_details(destination)
    logger.log_metric("source_disk_usage_percent", source_disk['usage_percent'], "percent")
    logger.log_metric("destination_disk_usage_percent", dest_disk['usage_percent'], "percent")
    
    print(f"  ✓ Sync configured: {source} → {destination} ({interval})")
