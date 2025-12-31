"""Data integrity checking with par2 and systemd timers."""

import os
import shlex
import hashlib
from typing import List

from lib.config import SetupConfig
from lib.setup_common import REMOTE_INSTALL_DIR
from lib.remote_utils import run, is_package_installed
from lib.mount_utils import is_path_under_mnt, get_mount_ancestor
from lib.task_utils import (
    validate_frequency,
    get_timer_calendar,
    escape_systemd_description,
    check_path_on_smb_mount
)


def install_par2(config: SetupConfig) -> None:
    """Install par2cmdline if not already installed."""
    if is_package_installed("par2"):
        print("  ✓ par2 already installed")
        return
    
    run("apt-get install -y -qq par2")
    print("  ✓ par2 installed")


def parse_scrub_spec(scrub_spec: List[str]) -> dict:
    """Parse scrub specification.
    
    Args:
        scrub_spec: [directory, database_path, redundancy, frequency]
        
    Returns:
        dict with 'directory', 'database_path', 'redundancy', 'frequency'
    """
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


def create_scrub_service(config: SetupConfig, scrub_spec: List[str] = None, **_) -> None:
    """Create par2 systemd service and timer for data integrity checking.
    
    Args:
        config: SetupConfig object
        scrub_spec: [directory, database_path, redundancy, frequency]
    """
    scrub_config = parse_scrub_spec(scrub_spec)
    
    directory = scrub_config['directory']
    database_path = scrub_config['database_path']
    redundancy = scrub_config['redundancy']
    frequency = scrub_config['frequency']
    
    path_hash = hashlib.md5(f"{directory}:{database_path}".encode()).hexdigest()[:8]
    safe_dir = directory.replace('/', '_').strip('_')
    service_name = f"scrub-{safe_dir}-{path_hash}"
    
    if not os.path.exists(directory):
        if is_path_under_mnt(directory):
            mount_ancestor = get_mount_ancestor(directory)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Directory {directory} is under /mnt but no mount point found")
                print(f"    Skipping directory creation - ensure mount is configured first")
            else:
                print(f"    Creating subdirectory under mount: {directory}")
                os.makedirs(directory, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(directory)}")
        else:
            print(f"  ⚠ Warning: Directory does not exist: {directory}")
            print(f"    Creating directory: {directory}")
            os.makedirs(directory, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(directory)}")
    
    db_parent = os.path.dirname(database_path)
    if db_parent and not os.path.exists(db_parent):
        if is_path_under_mnt(db_parent):
            mount_ancestor = get_mount_ancestor(db_parent)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Database parent {db_parent} is under /mnt but no mount point found")
                print(f"    Skipping directory creation - ensure mount is configured first")
            else:
                print(f"    Creating database directory under mount: {db_parent}")
                os.makedirs(db_parent, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(db_parent)}")
        else:
            print(f"    Creating database directory: {db_parent}")
            os.makedirs(db_parent, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(db_parent)}")
    
    escaped_directory = escape_systemd_description(directory)
    
    dir_on_smb = check_path_on_smb_mount(directory, config)
    db_on_smb = check_path_on_smb_mount(database_path, config)
    dir_under_mnt = is_path_under_mnt(directory)
    db_under_mnt = is_path_under_mnt(database_path)
    
    needs_mount_check = dir_on_smb or db_on_smb or dir_under_mnt or db_under_mnt
    
    log_dir = "/var/log/scrub"
    log_file = f"{log_dir}/{service_name}.log"
    
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    scrub_script = f"{REMOTE_INSTALL_DIR}/service_tools/scrub_par2.py"
    redundancy_value = redundancy[:-1]
    
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    if needs_mount_check:
        check_script = f"{REMOTE_INSTALL_DIR}/steps/check_scrub_mounts.py"
        
        service_content = f"""[Unit]
Description=Data integrity check for {escaped_directory}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
ExecCondition=/usr/bin/python3 {check_script} {shlex.quote(directory)} {shlex.quote(database_path)}
ExecStart=/usr/bin/python3 {scrub_script} {shlex.quote(directory)} {shlex.quote(database_path)} {shlex.quote(redundancy_value)} {shlex.quote(log_file)}
StandardOutput=journal
StandardError=journal
"""
    else:
        service_content = f"""[Unit]
Description=Data integrity check for {escaped_directory}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
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
    
    print(f"  ℹ Performing initial par2 creation (fast mode)...")
    
    result = run(
        f"/usr/bin/python3 {scrub_script} {shlex.quote(directory)} {shlex.quote(database_path)} "
        f"{shlex.quote(redundancy_value)} {shlex.quote(log_file)} --no-verify",
        check=False
    )
    
    if result.returncode == 0:
        print(f"  ✓ Initial par2 creation completed")
    else:
        print(f"  ⚠ Warning: Initial par2 creation may have encountered issues")
        if result.stderr:
            print(f"    Error details: {result.stderr.strip()}")
        if result.stdout:
            print(f"    Output: {result.stdout.strip()}")
    
    run("systemctl daemon-reload")
    run(f"systemctl enable {shlex.quote(service_name)}.timer")
    run(f"systemctl start {shlex.quote(service_name)}.timer")
    
    print(f"  ✓ Enabled and started timer")
    
    result = run(f"systemctl list-timers {shlex.quote(service_name)}.timer --no-pager", check=False)
    if result.returncode == 0:
        print(f"  ℹ Timer status:")
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                print(f"    {line}")
    
    print(f"  ✓ Scrub configured: {directory} (redundancy: {redundancy}, frequency: {frequency})")
    print(f"  ℹ Logs: {log_file}")

