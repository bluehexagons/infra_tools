"""Directory synchronization with rsync and systemd timers."""

from __future__ import annotations

import os
import time
from typing import Optional, Any

from lib.config import SetupConfig
from lib.remote_utils import run, is_package_installed
from lib.mount_utils import validate_mount_for_sync, validate_smb_connectivity, is_path_under_mnt
from lib.disk_utils import get_disk_usage_details
from lib.validation import validate_filesystem_path
from lib.operation_log import create_operation_logger
from lib.transaction import create_transaction
from lib.task_utils import (
    validate_frequency,
    check_path_on_smb_mount,
    ensure_directory
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
        
    except Exception as e:
        logger.log_error("sync_setup_error", str(e))
        if transaction:
            transaction.rollback(str(e))
        raise
    
    ensure_directory(source, config.username)
    
    dest_parent = os.path.dirname(destination)
    if dest_parent:
        ensure_directory(dest_parent, config.username)
    
    source_on_smb = check_path_on_smb_mount(source, config)
    dest_on_smb = check_path_on_smb_mount(destination, config)
    source_under_mnt = is_path_under_mnt(source)
    dest_under_mnt = is_path_under_mnt(destination)
    
    if source_on_smb or dest_on_smb:
        logger.log_step("mount_validation_enhanced", "started", "Performing enhanced mount validation")
        if source_on_smb:
            logger.log_metric("source_smb_connectivity", validate_smb_connectivity(source))
        if dest_on_smb:
            logger.log_metric("destination_smb_connectivity", validate_smb_connectivity(destination))
        logger.log_step("mount_validation_enhanced", "completed", "Enhanced mount validation completed")
    
    print(f"  ✓ Sync spec validated: {source} → {destination}")
    
    # Perform initial sync
    print(f"  ℹ Performing initial sync...")
    
    def perform_initial_sync():
        from sync.service_tools.sync_rsync import run_rsync_with_notifications
        result = run_rsync_with_notifications(source, destination)
        if result != 0:
            raise RuntimeError(f"Initial sync failed with exit code {result}")
        return True
    
    try:
        transaction.add_step(perform_initial_sync, lambda: None, "Initial sync", "initial_sync")
        
        if not transaction.execute():
            logger.log_error("initial_sync_failed", "Initial sync failed")
            transaction.rollback("Initial sync failed")
        else:
            logger.log_step("initial_sync", "completed", "Initial sync successful")
        
        logger.complete("completed", "Sync configured")
        
    except Exception as e:
        logger.log_error("initial_sync_error", str(e))
        if transaction:
            transaction.rollback(str(e))
    
    source_disk = get_disk_usage_details(source)
    dest_disk = get_disk_usage_details(destination)
    logger.log_metric("source_disk_usage_percent", source_disk['usage_percent'], "percent")
    logger.log_metric("destination_disk_usage_percent", dest_disk['usage_percent'], "percent")
    
    print(f"  ✓ Sync configured: {source} → {destination} ({interval})")
