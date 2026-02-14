"""Data integrity checking with par2 and systemd timers."""

from __future__ import annotations

import os
import shlex
import hashlib
import time
from typing import Optional, Any

from lib.config import SetupConfig
from lib.setup_common import REMOTE_INSTALL_DIR
from lib.remote_utils import run, is_package_installed
from lib.mount_utils import validate_mount_for_sync, validate_smb_connectivity, is_path_under_mnt
from lib.disk_utils import get_disk_usage_details
from lib.validation import (
    validate_filesystem_path, 
    validate_database_path, 
    validate_redundancy_percentage,
    validate_service_name_uniqueness
)
from lib.operation_log import create_operation_logger
from lib.transaction import create_transaction
from lib.service_manager import ServiceManager
from lib.task_utils import (
    validate_frequency,
    get_timer_calendar,
    escape_systemd_description,
    check_path_on_smb_mount,
    ensure_directory
)
from lib.systemd_service import cleanup_service


def install_par2(config: SetupConfig) -> None:
    if is_package_installed("par2"):
        print("  ✓ par2 already installed")
        return
    
    run("apt-get install -y -qq par2")
    print("  ✓ par2 installed")

def parse_scrub_spec(scrub_spec: list[str]) -> dict[str, Any]:
    if len(scrub_spec) != 4:
        raise ValueError(f"Invalid scrub spec: expected 4 arguments, got {len(scrub_spec)}")
    
    directory, database_path, redundancy, frequency = scrub_spec
    
    if not directory.startswith('/'):
        raise ValueError(f"Directory path must be absolute: {directory}")
    
    if not database_path.startswith('/'):
        database_path = os.path.join(directory, database_path)
    
    database_path = os.path.normpath(database_path)
    
    if not redundancy.endswith('%'):
        raise ValueError(f"Redundancy must end with '%': {redundancy}")
    try:
        redundancy_value = int(redundancy[:-1])
        if redundancy_value < 1 or redundancy_value > 100:
            raise ValueError(f"Redundancy percentage must be between 1 and 100: {redundancy}")
    except ValueError as e:
        if "invalid literal" in str(e):
            raise ValueError(f"Invalid redundancy format: {redundancy}")
        raise
    
    validate_frequency(frequency)
    
    return {
        'directory': directory,
        'database_path': database_path,
        'redundancy': redundancy,
        'frequency': frequency
    }

def create_scrub_service(config: SetupConfig, scrub_spec: Optional[list[str]] = None, **_ : Any) -> None:
    if not scrub_spec:
        raise ValueError("scrub_spec is required")
    
    scrub_config = parse_scrub_spec(scrub_spec)
    
    directory: str = scrub_config['directory']
    database_path: str = scrub_config['database_path']
    redundancy: str = scrub_config['redundancy']
    frequency: str = scrub_config['frequency']
    logger = create_operation_logger("scrub", directory=directory, database_path=database_path, 
                                    redundancy=redundancy, frequency=frequency)
    transaction = create_transaction(f"scrub_{int(time.time())}", logger, timeout_seconds=3600)
    
    try:
        transaction.add_validation_step(
            lambda: validate_filesystem_path(directory, must_exist=True, check_writable=False),
            f"Validate directory path: {directory}",
            "validate_directory"
        )
        transaction.add_validation_step(
            lambda: validate_database_path(database_path),
            f"Validate database path: {database_path}",
            "validate_database"
        )
        transaction.add_validation_step(
            lambda: validate_mount_for_sync(directory, "directory"),
            f"Validate directory mount: {directory}",
            "validate_directory_mount"
        )
        transaction.add_validation_step(
            lambda: validate_mount_for_sync(database_path, "database"),
            f"Validate database mount: {database_path}",
            "validate_database_mount"
        )
        
        def validate_redundancy():
            redundancy_int = validate_redundancy_percentage(redundancy)
            if redundancy_int < 1 or redundancy_int > 100:
                raise ValueError(f"Redundancy percentage must be between 1 and 100: {redundancy_int}")
            return redundancy_int
        
        transaction.add_validation_step(
            validate_redundancy,
            f"Validate redundancy percentage: {redundancy}",
            "validate_redundancy"
        )
        
        if not transaction.execute():
            logger.log_error("validation_failed", "Pre-scrub validation failed")
            transaction.rollback("Validation failed")
            return
        
        logger.log_metric("validation_success", True)
        
        path_hash = hashlib.md5(f"{directory}:{database_path}".encode()).hexdigest()[:8]
        safe_dir = directory.replace('/', '_').strip('_')
        service_name = f"scrub-{safe_dir}-{path_hash}"
        
        if not validate_service_name_uniqueness(service_name, []):
            service_manager = ServiceManager(config)
            existing_services = service_manager.list_backup_services()
            if not validate_service_name_uniqueness(service_name, existing_services):
                raise ValueError(f"Service name '{service_name}' conflicts with existing service")
        
        logger.log_step("service_name_validation", "completed", f"Validated service name: {service_name}")
        
        # Clean up any existing service/timer with the same name before creating new ones
        # For scrub, this includes both the main timer and the optional -update timer
        cleanup_service(service_name)
        cleanup_service(f"{service_name}-update")
        logger.log_step("service_cleanup", "completed", f"Cleaned up existing service if present: {service_name}")
        
    except Exception as e:
        logger.log_error("scrub_setup_error", str(e))
        if transaction:
            transaction.rollback(str(e))
        raise
    
    ensure_directory(directory, config.username)
    
    db_parent = os.path.dirname(database_path)
    if db_parent:
        ensure_directory(db_parent, config.username)
    
    escaped_directory = escape_systemd_description(directory)
    
    dir_on_smb = check_path_on_smb_mount(directory, config)
    db_on_smb = check_path_on_smb_mount(database_path, config)
    dir_under_mnt = is_path_under_mnt(directory)
    db_under_mnt = is_path_under_mnt(database_path)
    
    needs_mount_check = dir_on_smb or db_on_smb or dir_under_mnt or db_under_mnt
    
    if dir_on_smb or db_on_smb:
        logger.log_step("mount_validation_enhanced", "started", "Performing enhanced mount validation")
        if dir_on_smb:
            logger.log_metric("directory_smb_connectivity", validate_smb_connectivity(directory))
        if db_on_smb:
            logger.log_metric("database_smb_connectivity", validate_smb_connectivity(database_path))
        logger.log_step("mount_validation_enhanced", "completed", "Enhanced mount validation completed")
    
    check_script = f"{REMOTE_INSTALL_DIR}/sync/service_tools/check_scrub_mounts.py"
    log_dir = "/var/log/scrub"
    log_file = f"{log_dir}/{service_name}.log"
    
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    scrub_script = f"{REMOTE_INSTALL_DIR}/sync/service_tools/scrub_par2.py"
    redundancy_value = redundancy[:-1]
    
    service_file = f"/etc/systemd/system/{service_name}.service"
    exec_condition = f"ExecCondition=/usr/bin/python3 {check_script} {shlex.quote(directory)} {shlex.quote(database_path)}" if needs_mount_check else ""
    
    service_content = f"""[Unit]
Description=Data integrity check for {escaped_directory}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
{exec_condition}
ExecStart=/usr/bin/python3 {scrub_script} {shlex.quote(directory)} {shlex.quote(database_path)} {shlex.quote(redundancy_value)} {shlex.quote(log_file)}
StandardOutput=journal
StandardError=journal
"""
    
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    print(f"  ✓ Created service: {service_name}.service")
    
    timer_file = f"/etc/systemd/system/{service_name}.timer"
    calendar = get_timer_calendar(frequency, hour_offset=3)
    
    timer_content = f"""[Unit]
Description=Timer for data integrity check of {escaped_directory} ({frequency})

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
    
    print(f"  ✓ Created timer: {service_name}.timer ({frequency})")

    update_service_name = None
    if frequency != "hourly":
        update_service_name = f"{service_name}-update"
        update_service_file = f"/etc/systemd/system/{update_service_name}.service"
        update_timer_file = f"/etc/systemd/system/{update_service_name}.timer"
        
        exec_condition_update = f"ExecCondition=/usr/bin/python3 {check_script} {shlex.quote(directory)} {shlex.quote(database_path)}" if needs_mount_check else ""
        
        update_service_content = f"""[Unit]
Description=Parity update check for {escaped_directory}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
{exec_condition_update}
ExecStart=/usr/bin/python3 {scrub_script} {shlex.quote(directory)} {shlex.quote(database_path)} {shlex.quote(redundancy_value)} {shlex.quote(log_file)} --no-verify
StandardOutput=journal
StandardError=journal
"""
        with open(update_service_file, 'w') as f:
            f.write(update_service_content)
        
        update_timer_content = f"""[Unit]
Description=Timer for parity updates of {escaped_directory} (hourly)

[Timer]
OnCalendar=*-*-* *:30:00
Persistent=true
AccuracySec=1m
Unit={update_service_name}.service

[Install]
WantedBy=timers.target
"""
        with open(update_timer_file, 'w') as f:
            f.write(update_timer_content)
        
        print(f"  ✓ Created parity update timer: {update_service_name}.timer (hourly)")
    
    print(f"  ℹ Performing initial par2 creation (fast mode)...")
    
    def perform_initial_par2():
        result = run(f"/usr/bin/python3 {scrub_script} {shlex.quote(directory)} {shlex.quote(database_path)} {shlex.quote(redundancy_value)} {shlex.quote(log_file)} --no-verify", check=False, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"Initial par2 creation failed: {result.stderr or result.stdout}")
        return result.stdout
    
    def rollback_initial_par2():
        try:
            for file in os.listdir(directory):
                if file.endswith('.par2'):
                    os.remove(os.path.join(directory, file))
        except Exception as e:
            logger.log_error("rollback_initial_par2_failed", str(e))
    
    try:
        transaction.add_step(perform_initial_par2, rollback_initial_par2, "Initial par2 creation", "initial_par2_creation")
        
        if not transaction.execute():
            logger.log_error("initial_par2_failed", "Initial par2 failed")
            transaction.rollback("Initial par2 failed")
        else:
            logger.log_step("initial_par2", "completed", "Initial par2 successful")
        
        logger.complete("completed", "Scrub service configured")
        
    except Exception as e:
        logger.log_error("initial_par2_error", str(e))
        if transaction:
            transaction.rollback(str(e))
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {shlex.quote(service_name)}.timer")
    run(f"systemctl start {shlex.quote(service_name)}.timer")
    if update_service_name:
        run(f"systemctl enable {shlex.quote(update_service_name)}.timer", check=False)
        run(f"systemctl start {shlex.quote(update_service_name)}.timer", check=False)
    
    dir_disk = get_disk_usage_details(directory)
    db_disk = get_disk_usage_details(os.path.dirname(database_path))
    logger.log_metric("directory_disk_usage_percent", dir_disk['usage_percent'], "percent")
    logger.log_metric("database_disk_usage_percent", db_disk['usage_percent'], "percent")
    
    print(f"  ✓ Scrub configured: {directory} ({redundancy}, {frequency})")
